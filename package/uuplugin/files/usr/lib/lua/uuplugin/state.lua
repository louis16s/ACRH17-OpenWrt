-- /proc/net/tcp 的解析，用来回答一个具体问题：插件的云端控制通道是不是真的
-- 建起来了。
--
-- 这里只做纯计算。文件读取和 readlink 由调用方传进来，所以 tests/test_uuplugin.py
-- 能用固定样本喂它，而不是只能在路由器上验证。页面之所以值得单独算这一项：
-- 进程活着不等于通道在，「已连接」写错方向比不写更糟，而 ESTABLISHED 只说明
-- 某条连接存在，必须再确认这条 socket 的 inode 属于插件的 fd，才能说是它连的。
--
-- /proc/net/tcp 的一行（表头之后）是：
--   sl local_address rem_address st tx:rx tr:tm->when retrnsmt uid timeout inode
-- 其中 local/rem 形如 0100007F:3E80（小端十六进制地址 + 四位十六进制端口），
-- st 为 01 表示 ESTABLISHED。

local M = {}

local function tokens(line)
	local out = {}
	for token in line:gmatch("%S+") do out[#out + 1] = token end
	return out
end

-- 把 text 里所有 "远端端口为 port 且已建立" 的 socket inode 收进 into。
-- 传 into 就能把 tcp 与 tcp6 两张表并进同一个集合。
function M.established_inodes(text, port, into)
	into = into or {}
	local want = string.format("%04X", port)

	for line in (text or ""):gmatch("[^\n]+") do
		local field = tokens(line)
		-- 表头的第一列是 "sl"，不是序号；用它把表头挡掉。
		if field[1] and field[1]:match("^%d+:$") and field[4] == "01" then
			local remote = field[3] and field[3]:match("(%x+)$")
			if remote and remote:upper() == want and field[10] then
				into[field[10]] = true
			end
		end
	end

	return into
end

-- 列出某个进程持有的 socket fd，形如 socket:[12345]。
-- 按 fd 序号扫而不是遍历 /proc/<pid>/fd：目录迭代在 nixio 里的返回约定不稳，
-- 而这里的上限 256 个描述符对这个进程远够用，代价是几百次 readlink。
function M.socket_links(pid, readlink, limit)
	local links = {}
	for fd = 0, (limit or 255) do
		local target = readlink("/proc/" .. pid .. "/fd/" .. fd)
		if target and target:match("^socket:%[%d+%]$") then
			links[#links + 1] = target
		end
	end
	return links
end

-- inodes 里有任意一个出现在 links 里，就算这个进程拥有那条连接。
function M.owned(inodes, links)
	for _, link in ipairs(links) do
		local inode = link:match("%[(%d+)%]")
		if inode and inodes[inode] then return true end
	end
	return false
end

-- 任意一个 pid 拥有指向 port 的 ESTABLISHED 连接。
function M.cloud_connected(pids, tables, port, readlink)
	local inodes = {}
	for _, text in ipairs(tables or {}) do
		M.established_inodes(text, port, inodes)
	end
	if not next(inodes) then return false end

	for _, pid in ipairs(pids or {}) do
		if M.owned(inodes, M.socket_links(pid, readlink)) then return true end
	end
	return false
end

return M
