# RT-ACRH17 OpenWrt 24.10

Target: ASUS RT-ACRH17, which OpenWrt identifies under the `asus_rt-ac42u` device definition.

Included in this first build:
- LuCI + HTTPS + ttyd
- UA3F with LuCI
- Ruijie/ePortal authentication with LuCI GUI and automatic reconnect
- mwan3 + LuCI
- Android USB tethering (RNDIS / CDC Ethernet / NCM)
- ZTE F50 compatibility modules including CDC Ethernet/NCM/MBIM
- USB printer kernel driver + p910nd + LuCI
- BBR
- zram-swap

Intentionally omitted:
- Clash / OpenClash
- AdGuard Home
- Samba
- Docker
- MiniEAP
- 160 MHz wireless patches
- ART/calibration modifications

## Build on GitHub

1. Create an empty GitHub repository.
2. Upload this repository content.
3. Open `Actions`.
4. Select `Build RT-ACRH17 OpenWrt`.
5. Click `Run workflow`.
6. Download the `RT-ACRH17-OpenWrt-24.10` artifact.

## OpBoot flashing note

Do not modify or erase ART/calibration/bootloader partitions.

This workflow deliberately builds the standard OpenWrt images for `asus_rt-ac42u`.
Before flashing through OpBoot, verify which image type your OpBoot page accepts.
Do not blindly flash a sysupgrade image into a field that expects a vendor/factory image.

For first boot testing, an initramfs image is preferable when OpBoot supports loading it without writing permanent firmware.
After confirming Ethernet, Wi-Fi and LuCI work, use the appropriate sysupgrade image for permanent installation.

## USB tethering

After connecting an Android phone or ZTE F50:

```sh
ip -br link
dmesg | grep -Ei 'rndis|cdc|ncm|mbim|usb'
```

If a new interface such as `usb0` or `eth2` appears, create a LuCI interface:
- Network -> Interfaces -> Add new interface
- Name: `usbwan`
- Protocol: DHCP client
- Device: the detected USB network device

Then add `wan` and `usbwan` to mwan3.

## USB printer

Connect a USB printer and check:

```sh
ls -l /dev/usb/
```

If `/dev/usb/lp0` exists:
- Services -> p910nd
- Enable
- Device: `/dev/usb/lp0`
- Port: `0` (TCP 9100)

The actual vendor printer driver remains installed on Windows/macOS; OpenWrt only provides the RAW network print transport.

## UA3F

Open:
- Services -> UA3F

This build includes nftables dependencies used by UA3F.

## Ruijie GUI

Open `Services -> Ruijie ePortal`. Fill the fields from a successful browser login request: server, userId, captured password payload, service, queryString, Cookie and Referer. Use **Login now** to test. Enable automatic authentication only after manual login succeeds.
