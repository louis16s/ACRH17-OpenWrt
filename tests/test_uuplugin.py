"""UU 插件的三块可离线验证的部分：包接线、启动脚本的状态迁移、通道判据。

真机上的东西（云端 :16000 通道、nft 下发、App 绑定）不在这里，但凡是能在本机
证伪的都钉住：镜像里的文件是不是真装着、身份在 tmpfs 与 overlay 之间怎么搬、
某条 socket 到底算不算插件自己的。
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'package/uuplugin'
INIT = PKG / 'files/etc/init.d/uuplugin'
STATE = PKG / 'files/usr/lib/lua/uuplugin/state.lua'
MAKEFILE = PKG / 'Makefile'


class PackageWiringTests(unittest.TestCase):
    def test_every_packaged_file_is_installed(self):
        # 写了文件却忘了在 install 里装，是这里最容易犯的错，而它只在镜像里
        # 才暴露：页面上少一个文件就是 500。
        makefile = MAKEFILE.read_text()
        for path in sorted((PKG / 'files').rglob('*')):
            if path.is_dir():
                continue
            with self.subTest(file=str(path.relative_to(PKG))):
                self.assertIn('./files/' + path.relative_to(PKG / 'files').as_posix(),
                              makefile)

    def test_the_download_is_pinned_by_version_and_hash(self):
        makefile = MAKEFILE.read_text()
        self.assertIn('PKG_SOURCE_URL:=http://uurouter.gdl.netease.com/uuplugin/openwrt-arm/v$(PKG_VERSION)',
                      makefile)
        # 24.10 的 download.mk 只把 PKG_HASH 接到 check_download_integrity 上，
        # PKG_MD5SUM 已经降级为一条警告。
        self.assertRegex(makefile, r'\nPKG_HASH:=[0-9a-f]{64}\n')
        self.assertNotRegex(makefile, r'(?m)^PKG_MD5SUM')
        # 二进制只有 arm 版本，包本身必须自我限定，别等交叉编译跑完才失败。
        self.assertIn('DEPENDS:=@arm', makefile)

    def test_prepare_copies_the_package_into_the_build_tree(self):
        self.assertIn('cp -R "$PROJECT/package/uuplugin" package/',
                      (ROOT / 'scripts/prepare.sh').read_text())

    def test_config_selects_the_package(self):
        self.assertIn('CONFIG_PACKAGE_uuplugin=y',
                      (ROOT / 'configs/acrh17.config').read_text())

    def test_identity_survives_sysupgrade(self):
        # /etc 不在默认 keep.d 清单里，这条规则缺了就是每次升级都要重绑。
        listed = {line.strip() for line in
                  (PKG / 'files/lib/upgrade/keep.d/uuplugin').read_text().splitlines()
                  if line.strip() and not line.startswith('#')}
        self.assertIn('/etc/uu', listed)


class InitScriptTests(unittest.TestCase):
    """真跑启动脚本里的状态迁移，路径重定向到沙箱。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.bin = self.dir / 'usr/lib/uu'
        self.run_dir = self.dir / 'tmp/uu'
        self.id_dir = self.dir / 'etc/uu/id'
        self.bin.mkdir(parents=True)
        for name in ('uuplugin', 'xuplugin-guardian', 'xtables-nft-multi'):
            (self.bin / name).write_text('binary\n')
            (self.bin / name).chmod(0o755)
        (self.bin / 'uu.conf').write_text('log_level=info\nversion=v14.10.6\n')

        self.script = self.dir / 'uuplugin.init'
        self.script.write_text(
            INIT.read_text()
            .replace('/usr/lib/uu', str(self.bin))
            .replace('/tmp/uu', str(self.run_dir))
            .replace('/etc/uu/id', str(self.id_dir)))

    def shell(self, body, **env):
        # 桩件在 source 之后定义也没问题：脚本本身只定义函数，调用发生在后面。
        prelude = '''. "%s"
uci() {
	case "$*" in
	*log_level*) echo "${LOG_LEVEL:-info}" ;;
	*enabled*) echo "${ENABLED:-1}" ;;
	esac
}
logger() { case "$*" in *missing*) echo "LOG $*" >&2 ;; esac; }
killall() { :; }
pidof() { return 1; }
nft() { :; }
sleep() { :; }
procd_open_instance() { echo "OPEN"; }
procd_set_param() { echo "PARAM $*"; }
procd_close_instance() { echo "CLOSE"; }
''' % self.script
        return subprocess.run(['sh', '-c', prelude + body], text=True,
                              capture_output=True, timeout=30,
                              env=dict(os.environ, **env))

    def prepare(self, **env):
        return self.shell('\nprepare\necho "rc=$?"\n', **env)

    def test_prepare_stages_the_binaries_into_tmp(self):
        result = self.prepare()
        self.assertIn('rc=0', result.stdout, result.stderr)
        for name in ('uuplugin', 'xuplugin-guardian', 'xtables-nft-multi'):
            staged = self.run_dir / name
            self.assertTrue(staged.is_file(), name)
            self.assertTrue(os.access(staged, os.X_OK), name)
        self.assertTrue((self.run_dir / 'uu.conf').is_file())
        self.assertEqual(self.id_dir.stat().st_mode & 0o777, 0o700)

    def test_prepare_backfills_a_saved_identity(self):
        # tmpfs 清空后不接受回填，插件就会重新生成身份，云端把它当新设备。
        self.id_dir.mkdir(parents=True)
        (self.id_dir / '.sn').write_text('AA:BB:CC:DD:EE:FF.uuid\n')
        (self.id_dir / '.uuplugin_uuid').write_text('uuid-1234\n')
        self.assertIn('rc=0', self.prepare().stdout)
        self.assertEqual((self.run_dir / '.sn').read_text(), 'AA:BB:CC:DD:EE:FF.uuid\n')
        self.assertEqual((self.run_dir / '.uuplugin_uuid').read_text(), 'uuid-1234\n')
        self.assertEqual((self.run_dir / '.sn').stat().st_mode & 0o777, 0o600)

    def test_prepare_fails_loudly_when_a_binary_is_missing(self):
        (self.bin / 'xuplugin-guardian').unlink()
        result = self.prepare()
        self.assertIn('rc=1', result.stdout)
        self.assertIn('missing', result.stderr)

    def test_log_level_comes_from_uci_and_the_version_line_survives(self):
        self.assertIn('rc=0', self.prepare(LOG_LEVEL='debug').stdout)
        conf = (self.run_dir / 'uu.conf').read_text().splitlines()
        self.assertIn('log_level=debug', conf)
        self.assertIn('version=v14.10.6', conf)

    def test_an_unknown_log_level_leaves_the_copy_alone(self):
        # 闭源程序读的是这张表里的值；写进去一个它不认识的字符串，换来的
        # 只是没人解释得清的行为。
        self.assertIn('rc=0', self.prepare(LOG_LEVEL='verbose').stdout)
        self.assertIn('log_level=info',
                      (self.run_dir / 'uu.conf').read_text().splitlines())

    def test_save_id_writes_the_live_identity_back(self):
        self.run_dir.mkdir(parents=True)
        (self.run_dir / '.sn').write_text('NEW-SN\n')
        (self.run_dir / 'activate_status').write_text('1\n')
        self.shell('\nsave_id\necho "rc=$?"\n')
        self.assertEqual((self.id_dir / '.sn').read_text(), 'NEW-SN\n')
        self.assertEqual((self.id_dir / 'activate_status').read_text(), '1\n')
        self.assertEqual((self.id_dir / '.sn').stat().st_mode & 0o777, 0o600)

    def test_stop_saves_the_identity_before_shutdown(self):
        # sysupgrade 和 reboot 都走 stop_service，这是身份唯一的回写时机。
        self.run_dir.mkdir(parents=True)
        (self.run_dir / '.sn').write_text('REBOUND-SN\n')
        (self.run_dir / 'activate_status').write_text('1\n')
        for name in ('uuplugin', 'xuplugin-guardian', 'xtables-nft-multi'):
            (self.run_dir / name).write_text('binary\n')
        self.shell('\nstop_service\n')
        self.assertEqual((self.id_dir / '.sn').read_text(), 'REBOUND-SN\n')
        # 运行目录是 tmpfs 里的三份二进制副本（约 6.5 MB 内存），服务停着的时候
        # 没有理由继续占着。身份在上面已经写回 /etc/uu/id，删掉不会丢绑定。
        self.assertFalse(self.run_dir.exists())

    def test_start_honours_the_enabled_flag(self):
        result = self.shell('\nstart_service\n', ENABLED='0')
        self.assertNotIn('OPEN', result.stdout)
        self.assertEqual(result.returncode, 0)

    def test_start_runs_the_binary_from_the_writable_directory(self):
        # 插件以 cwd 定位 uu.conf 和身份文件，并且会 fork 同目录的守护进程；
        # cwd 不对，它读到的就是另一份东西。
        result = self.shell('\nstart_service\n', ENABLED='1')
        self.assertIn('OPEN', result.stdout)
        command = [line for line in result.stdout.splitlines() if line.startswith('PARAM command')]
        self.assertTrue(command, result.stdout)
        self.assertIn('ulimit -HS -s 8192', command[0])
        self.assertIn('cd %s' % self.run_dir, command[0])
        self.assertIn('exec ./uuplugin ./uu.conf', command[0])


class CloudChannelTests(unittest.TestCase):
    """/proc/net/tcp 的解析用 lua 直接跑 state.lua，不经过路由器。"""

    TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 11111 1 0 0 10 0
   1: 0100007F:9F63 0A00020F:3E80 01 00000000:00000000 00:00000000 00000000     0        0 22222 1 0 0 20 4
   2: 0100007F:9F64 0A00020F:3E80 06 00000000:00000000 00:00000000 00000000     0        0 33333 1 0 0 20 4
   3: 0100007F:9F65 0A00020F:0050 01 00000000:00000000 00:00000000 00000000     0        0 44444 1 0 0 20 4
"""
    TCP6 = """  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000000000000000000000000000:0000 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 66666 1 0 0 10 0
   1: 00000000000000000000000001000000:1F90 0000000000000000FFFF00000A00020F:3e80 01 00000000:00000000 00:00000000 00000000     0        0 55555 1 0 0 20 4
"""

    def setUp(self):
        self.lua = shutil.which('lua5.1') or shutil.which('lua')
        if not self.lua:
            self.skipTest('no lua interpreter to exercise state.lua')

    def run_lua(self, body):
        # 路径直接放进双引号里：json.dumps 会写成 \u8... 转义，lua 不认。
        source = 'local state = dofile("%s")\n' % STATE.as_posix() + body
        result = subprocess.run([self.lua, '-'], input=source, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)

    def test_only_established_connections_to_the_control_port_count(self):
        out = self.run_lua("""
local function keys(set)
	local out = {}
	for k in pairs(set) do out[#out + 1] = k end
	table.sort(out)
	return table.concat(out, ",")
end
print("established=" .. keys(state.established_inodes([==[%s]==], 16000)))
print("other_port=" .. keys(state.established_inodes([==[%s]==], 80)))
""" % (self.TCP, self.TCP))
        # LISTEN(0A)、TIME_WAIT(06) 与别的端口都不是「已连接」。
        self.assertEqual(out['established'], '22222')
        self.assertEqual(out['other_port'], '44444')

    def test_the_hex_port_is_matched_case_insensitively(self):
        out = self.run_lua("""
local function keys(set)
	local out = {}
	for k in pairs(set) do out[#out + 1] = k end
	table.sort(out)
	return table.concat(out, ",")
end
print("tcp6=" .. keys(state.established_inodes([==[%s]==], 16000)))
""" % self.TCP6)
        # 内核写的是大写，但没理由依赖这一点。
        self.assertEqual(out['tcp6'], '55555')

    def test_a_connection_belongs_to_the_process_that_holds_it(self):
        # 只看端口会把别人的连接算到插件头上，方向错在更危险的那一侧。
        out = self.run_lua("""
local fd = {
	["/proc/900/fd/0"] = "/dev/null",
	["/proc/900/fd/3"] = "socket:[22222]",
	["/proc/900/fd/4"] = "socket:[99999]",
	["/proc/900/fd/5"] = "pipe:[7]",
}
local function readlink(path) return fd[path] end
local inodes = state.established_inodes([==[%s]==], 16000)
local links = state.socket_links("900", readlink)
print("links=" .. #links)
print("owned=" .. tostring(state.owned(inodes, links)))
print("stranger=" .. tostring(state.owned(inodes, state.socket_links("901", readlink))))
print("alive=" .. tostring(state.cloud_connected({"901", "900"}, {[==[%s]==]}, 16000, readlink)))
print("dead=" .. tostring(state.cloud_connected({"900"}, {[==[%s]==]}, 16000, function() return nil end)))
""" % (self.TCP, self.TCP, self.TCP))
        self.assertEqual(out['links'], '2', 'only the socket links should be collected')
        self.assertEqual(out['owned'], 'true')
        self.assertEqual(out['stranger'], 'false')
        # 两个 pid 里有一个持有就算连上：守护进程也可能自己建这条连接。
        self.assertEqual(out['alive'], 'true')
        self.assertEqual(out['dead'], 'false')


class PageWiringTests(unittest.TestCase):
    """模板与 CBI 模型之间的字段约定，静态核对。

    LuCI 在模板里读一个模型没赋值的 self.X 只会得到 nil，页面照样 200——少一个
    Template 目标文件却是运行时 500。这两类错都能在这里挡住，不用等路由器。
    """

    def setUp(self):
        self.model = (PKG / 'files/usr/lib/lua/luci/model/cbi/uuplugin.lua').read_text()

    def test_templates_only_read_fields_the_model_sets(self):
        for name, node in (('dashboard', 'dashboard'), ('logs', 'logs')):
            template = (PKG / 'files/usr/lib/lua/luci/view/uuplugin' / (name + '.htm')).read_text()
            read = set(re.findall(r'self\.([A-Za-z_]\w*)', template))
            written = set(re.findall(r'%s\.([A-Za-z_]\w*)\s*=' % node, self.model))
            with self.subTest(template=name):
                self.assertTrue(read, 'no self.* fields found in the template')
                self.assertEqual(read - written, set())

    def test_every_template_target_exists(self):
        for target in re.findall(r'Template\("([^"]+)"\)', self.model):
            with self.subTest(view=target):
                self.assertTrue(
                    (PKG / 'files/usr/lib/lua/luci/view' / (target + '.htm')).is_file())

    def test_the_menu_entry_points_at_this_model(self):
        controller = (PKG / 'files/usr/lib/lua/luci/controller/uuplugin.lua').read_text()
        for model in re.findall(r'cbi\("([^"]+)"\)', controller):
            with self.subTest(model=model):
                self.assertTrue(
                    (PKG / 'files/usr/lib/lua/luci/model/cbi' / (model + '.lua')).is_file())
        self.assertIn('"/etc/config/uuplugin"', controller)


class PackageRecipeTests(unittest.TestCase):
    """把 Makefile 里的配方本身跑一遍。

    make 对这些配方做的事只有变量展开，然后交给 sh，所以这里用同样方式执行：
    这样可以证明镜像里的布局与权限，而不用等一次完整构建。归档用合成包代替，
    形状与官方包一致——四个文件、没有 pkg-version/ 这一层容器目录。
    """

    FILES = ('uuplugin', 'xuplugin-guardian', 'xtables-nft-multi', 'uu.conf')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.dl = self.dir / 'dl'
        self.build = self.dir / 'build/uuplugin-14.10.6'
        self.root = self.dir / 'root'
        self.dl.mkdir(parents=True)
        # 故意不建 $(PKG_BUILD_DIR)：覆盖 Build/Prepare 之后没有别人建它，
        # 配方里少了 mkdir -p 就该在这里失败，而不是等到真构建才暴露。

        source = self.dir / 'src'
        source.mkdir()
        for name in self.FILES:
            (source / name).write_text('payload\n')
        archive = self.dl / 'uu.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for name in self.FILES:
                tar.add(source / name, arcname=name)

    def recipe(self, name):
        text = MAKEFILE.read_text().split('define %s\n' % name, 1)[1].split('\nendef', 1)[0]
        lines = [line[1:] if line.startswith('\t') else line for line in text.splitlines()]
        # make 吃掉行首的 @（不回显），sh 不认识它。
        lines = [line[1:] if line.startswith('@') else line for line in lines]
        for line in lines:
            for key, value in {
                '$(TAR)': 'tar',
                '$(DL_DIR)': str(self.dl),
                '$(PKG_SOURCE)': 'uu.tar.gz',
                '$(PKG_BUILD_DIR)': str(self.build),
                # rules.mk 的原值：INSTALL_CONF 是 0600，不是 0644。
                '$(INSTALL_DIR)': 'install -d -m0755',
                '$(INSTALL_BIN)': 'install -m0755',
                '$(INSTALL_DATA)': 'install -m0644',
                '$(INSTALL_CONF)': 'install -m0600',
                '$(1)': str(self.root),
            }.items():
                line = line.replace(key, value)
            line = line.replace('$$', '$')
            # OpenWrt 对配方展开两次：define 里的 $$ 第一次变成 $，写进 recipe
            # 时再展开一次，`$f` 就成了空的 make 变量。曾因此让构建在
            # `[ -f $(PKG_BUILD_DIR)/ ]` 上恒假、每个包都报缺文件。所以配方里
            # 不留任何 $——需要的东西全部交给 make 展开，shell 只负责执行。
            self.assertNotIn('$', line, '配方在第二次展开后残留 $：%s' % line)
            yield line

    def run_recipe(self, name):
        result = subprocess.run(['sh', '-e', '-'], input='\n'.join(self.recipe(name)),
                                text=True, capture_output=True, cwd=PKG, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_prepare_unpacks_into_the_build_directory(self):
        # 默认解包会往 $(PKG_BUILD_DIR)/.. 展开，那会把四个文件撒到 build_dir 里。
        self.run_recipe('Build/Prepare')
        self.assertEqual(sorted(p.name for p in self.build.iterdir()), sorted(self.FILES))

    def test_prepare_rejects_an_archive_without_all_four_files(self):
        # 归档形状变了就该在解包这一步停下，而不是装出一个缺二进制的包。
        with tarfile.open(self.dl / 'uu.tar.gz', 'w:gz') as tar:
            tar.add(self.dir / 'src/uuplugin', arcname='uuplugin')
        with self.assertRaises(AssertionError):
            self.run_recipe('Build/Prepare')

    def test_install_produces_exactly_the_expected_tree(self):
        self.run_recipe('Build/Prepare')
        self.run_recipe('Package/uuplugin/install')

        installed = {p.relative_to(self.root).as_posix()
                     for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(installed, {
            'usr/lib/uu/uuplugin',
            'usr/lib/uu/xuplugin-guardian',
            'usr/lib/uu/xtables-nft-multi',
            'usr/lib/uu/uu.conf',
            'etc/init.d/uuplugin',
            'etc/config/uuplugin',
            'lib/upgrade/keep.d/uuplugin',
            'usr/lib/lua/uuplugin/state.lua',
            'usr/lib/lua/luci/controller/uuplugin.lua',
            'usr/lib/lua/luci/model/cbi/uuplugin.lua',
            'usr/lib/lua/luci/view/uuplugin/dashboard.htm',
            'usr/lib/lua/luci/view/uuplugin/logs.htm',
            'www/luci-static/resources/uuplugin/dashboard.css',
        })
        for path in ('usr/lib/uu/uuplugin', 'etc/init.d/uuplugin'):
            self.assertTrue(os.access(self.root / path, os.X_OK), path)
        self.assertFalse(os.access(self.root / 'usr/lib/uu/uu.conf', os.X_OK))
        # 配置走 INSTALL_CONF（0600），二进制 0755，页面的 lua/css 是只读数据。
        self.assertEqual((self.root / 'etc/config/uuplugin').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / 'usr/lib/uu/uu.conf').stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.root / 'usr/lib/lua/uuplugin/state.lua').stat().st_mode & 0o777,
                         0o644)


if __name__ == '__main__':
    unittest.main()
