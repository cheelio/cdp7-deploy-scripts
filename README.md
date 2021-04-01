libvirt notes
=============
- Make sure setting 'dynamic_ownership = 0' is set in /etc/libvirt/qemu.conf
- Uncomment user = "root" and group = "root" in /etc/libvirt/qemu.conf`` 
- Make sure linux kernel is readable: sudo chmod +r /boot/vmlinuz-*
