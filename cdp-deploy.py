#!/usr/bin/env python3
import getpass
import tarfile
import os
import socket
import subprocess
import time
from distutils.dir_util import copy_tree
from pathlib import Path
from shutil import copyfile
import downloader
import libvirt
import yaml
from jinja2 import Template
from pathlib import Path

config = yaml.load(open("config.yaml"), Loader=yaml.FullLoader)
USER = getpass.getuser()
DISK_IMAGE = config.get("general").get("diskImage")
DISK_IMAGE_URL = config.get("general").get("diskImageUrlPrefix") + DISK_IMAGE
NETWORK_NAME = config.get("general").get("networkName")
VM_USER_NAME = config.get("general").get("username")
IP_CM = config.get("cmNode").get("ip")
MAC_CM = config.get("cmNode").get("mac")
HOSTNAME_CM = config.get("cmNode").get("hostname")
CM_VERSION = config.get('general').get('cmVersion')
CDH_FULL_PARCEL_VERSION = config.get("general").get("cdhParcelFullVersion")
CDH_PARCEL_VERSION = config.get("general").get("cdhParcelVersion")
libvirtConn = libvirt.open(None)


def install_requirements():
    print("Installing requirements...")
    run_cmd('apt-get install -y cloud-image-utils python3-pip libguestfs-tools')
    run_cmd('pip3 install -r requirements.txt')


def prepare_config_file():
    if not os.path.isfile("work/id_rsa"):
        run_cmd('ssh-keygen -t rsa -b 4096 -f work/id_rsa -C cdh7 -N "" -q')
    public_key = open("work/id_rsa.pub", "r").read()
    new_text = open("config.yaml").read().replace('PUBLIC_KEY_PLACEHOLDER', public_key)
    open("work/config-final.yaml", "w").write(new_text)
    global config
    config = yaml.load(open("work/config-final.yaml"), Loader=yaml.FullLoader)


def cleanup():
    print("Cleanup host...")
    clean_host(HOSTNAME_CM)
    if config.get("dataNodes"):
        for dataNode in config.get("dataNodes"):
            clean_host(dataNode.get("hostname"))
            if os.path.exists("work/" + DISK_IMAGE):
                vm_image = "work/" + dataNode.get("hostname") + "-" + DISK_IMAGE
                if os.path.exists(vm_image):
                    os.remove(vm_image)

    print("Cleanup network...")
    if len([network for network in libvirtConn.listAllNetworks() if network.name() == NETWORK_NAME]) == 1:
        try:
            network = libvirtConn.networkLookupByName(NETWORK_NAME)
            network.destroy()
            network.undefine()
        except libvirt.libvirtError:
            pass

    if os.path.exists("work/" + DISK_IMAGE):
        os.remove("work/" + DISK_IMAGE)


def clean_host(machine_name):
    try:
        domain = libvirtConn.lookupByName(machine_name)
        if domain is not None:
            try:
                domain.destroy()
            except libvirt.libvirtError:
                pass
            domain.undefine()
    except libvirt.libvirtError:
        pass


def create_extra_images():
    print("Creating CM image...")
    download_or_resume('https://archive.cloudera.com/cm7/' + CM_VERSION + '/repo-as-tarball/cm' +
                       CM_VERSION + '-redhat7.tar.gz', 'work/cm' + CM_VERSION + '-redhat7.tar.gz')
    if not os.path.exists("work/" + HOSTNAME_CM + "-cm" + CM_VERSION + "-redhat7.qcow2"):
        run_cmd("virt-make-fs --format=qcow2 work/cm" + CM_VERSION + "-redhat7.tar.gz work/" +
                HOSTNAME_CM + "-cm" + CM_VERSION + "-redhat7.qcow2")

    print("Creating config-files image...")
    copy_tree("config-files", "work/config-files")
    with open('work/config-files/cluster_template_base.json', 'w') as f:
        f.write(Template(open('templates/cluster_template_base.json.j2').read()).render(config))
    with open('work/config-files/cluster_template_full.json', 'w') as f:
        f.write(Template(open('templates/cluster_template_full.json.j2').read()).render(config))
    with open('work/config-files/cdp-deploy.sh', 'w') as f:
        f.write(Template(open('templates/cdp-deploy.sh.j2').read()).render(config))
    run_cmd("virt-make-fs --format=qcow2 work/config-files work/" + HOSTNAME_CM + "-config-files.qcow2")

    print("Creating Parcel image...")
    parcel_file_name = 'work/parcels/CDH-' + CDH_FULL_PARCEL_VERSION + '-el7.parcel'
    if not os.path.exists("work/parcels.qcow2"):
        if not os.path.exists("work/parcels"):
            os.mkdir("work/parcels")
        parcel_url = 'http://archive.cloudera.com/cdh7/' + CDH_PARCEL_VERSION + '/parcels/CDH-' + CDH_FULL_PARCEL_VERSION + '-el7.parcel'
        download_or_resume('%s' % parcel_url, parcel_file_name)
        run_cmd('tar -zxvf ' + parcel_file_name + " -C work/parcels/")
        download_or_resume('%s.sha1' % parcel_url, 'work/parcels/CDH-' + CDH_FULL_PARCEL_VERSION + '-el7.parcel.sha1')
        download_or_resume('%s.sha256' % parcel_url, 'work/parcels/CDH-' + CDH_FULL_PARCEL_VERSION + '-el7.parcel.sha256')
        download_or_resume('http://archive.cloudera.com/cdh7/' + CDH_PARCEL_VERSION + '/parcels/manifest.json', 'work/parcels/manifest.json')
        run_cmd('ln -s CDH-' + CDH_FULL_PARCEL_VERSION + ' work/parcels/CDH')
        run_cmd('touch work/parcels/CDH/.dont_delete')
        run_cmd('virt-make-fs --size=+20G --format=qcow2 work/parcels work/parcels.qcow2')

    if config.get("dataNodes"):
        for item in config.get("dataNodes"):
            if not os.path.exists("work/" + item.get("hostname") + "-cm" + CM_VERSION + "-redhat7.qcow2"):
                run_cmd("virt-make-fs --format=qcow2 work/cm" + CM_VERSION + "-redhat7.tar.gz work/"
                        + item.get("hostname") + "-cm" + CM_VERSION + "-redhat7.qcow2")
            run_cmd("virt-make-fs --format=qcow2 config-files work/" + item.get("hostname") + "-config-files.qcow2")


def download_or_resume(url, path):
    if os.path.exists(path):
        downloader.Download(url, path).resume()
    else:
        downloader.Download(url, path).download()


def get_os_image():
    print("Downloading QCOW CloudInit Image " + DISK_IMAGE + "...")
    download_or_resume(DISK_IMAGE_URL, "work/ORIGINAL_" + DISK_IMAGE)
    run_cmd('qemu-img resize work/ORIGINAL_' + DISK_IMAGE + ' 20G')


def make_cloudinit_image():
    print("Creating CloudInit Images...")
    with open('work/cloud_init_cmhost.cfg', 'w') as f:
        f.write(Template(open('templates/cloud_init_cmhost.cfg.j2').read()).render(config))
    with open('work/network_config_static.cfg', 'w') as f:
        f.write(Template(open('templates/network_config_static.cfg.j2').read()).render(config))

    if os.path.exists("work/" + HOSTNAME_CM + "-seed.qcow2"):
        os.remove("work/" + HOSTNAME_CM + "-seed.qcow2")

    run_cmd("cloud-localds --network-config=work/network_config_static.cfg work/" + HOSTNAME_CM +
            "-seed.qcow2 work/cloud_init_cmhost.cfg")

    if config.get("dataNodes"):
        for dataNode in config.get("dataNodes"):
            with open('work/cloud_init_' + dataNode.get('hostname') + '.cfg', 'w') as f:
                f.write(Template(open('templates/cloud_init_datanode.cfg.j2').read()).render({**config, **dataNode}))
            run_cmd("cloud-localds --network-config=work/network_config_static.cfg work/" + dataNode.get("hostname") +
                    "-seed.qcow2 work/cloud_init_" + dataNode.get("hostname") + ".cfg")


def restore_os_image():
    print("Restoring QCOW CloudInit Images...")
    copyfile("work/ORIGINAL_" + DISK_IMAGE, "work/" + HOSTNAME_CM + "-" + DISK_IMAGE)

    if config.get("dataNodes"):
        for item in config.get("dataNodes"):
            copyfile("work/ORIGINAL_" + DISK_IMAGE, "work/" + item.get("hostname") + "-" + DISK_IMAGE)


def create_network():
    print("creating network " + NETWORK_NAME + "...")
    open("work/virt-network-" + NETWORK_NAME, 'w').write(
        Template(open('templates/virt-network.j2').read()).render(config))
    libvirtConn.networkCreateXML(open("work/virt-network-" + NETWORK_NAME).read())


def create_vms():
    print("Starting VMs...")
    create_command = '''                                                                        \
    virt-install -q                                                                             \
    --name ''' + HOSTNAME_CM + '''                                                              \
    --virt-type kvm --memory 12288 --vcpus 4                                                    \
    --boot hd,menu=on                                                                           \
    --disk path=work/''' + HOSTNAME_CM + '''-seed.qcow2,device=cdrom                            \
    --disk path=work/''' + HOSTNAME_CM + "-" + DISK_IMAGE + ''',device=disk                     \
    --disk path=work/''' + HOSTNAME_CM + '''-cm''' + CM_VERSION + '''-redhat7.qcow2,device=disk \
    --disk path=work/''' + HOSTNAME_CM + '''-config-files.qcow2,device=disk                     \
    --disk path=work/parcels.qcow2,device=disk                                                  \
    --graphics vnc                                                                              \
    --network network:''' + NETWORK_NAME + '''                                                  \
    --mac=''' + MAC_CM + '''                                                                    \
    --os-variant=rhel7.0                                                                        \
    --noautoconsole                                                                             \
    --console pty,target_type=serial'''
    run_cmd(create_command)
    run_cmd("ssh-keygen -f " + str(Path.home()) + "/.ssh/known_hosts -R " + IP_CM, True)

    if config.get("dataNodes"):
        for item in config.get("dataNodes"):
            create_command = '''                                                                                \
            virt-install -q                                                                                     \
            --name ''' + item.get("hostname") + '''                                                             \
            --virt-type kvm --memory 4096 --vcpus 2                                                             \
            --boot hd,menu=on                                                                                   \
            --disk path=work/''' + item.get("hostname") + '''-seed.qcow2,device=cdrom                           \
            --disk path=work/''' + item.get("hostname") + "-" + DISK_IMAGE + ''',device=disk                    \
            --disk path=work/''' + item.get("hostname") + '''-cm" + CM_VERSION + "-redhat7.qcow2,device=disk    \
            --disk path=work/''' + item.get("hostname") + '''-config-files.qcow2,device=disk                    \
            --graphics vnc                                                                                      \
            --network network:''' + NETWORK_NAME + '''                                                          \
            --mac=''' + item.get("mac") + '''                                                                   \
            --os-variant=rhel7.0                                                                                \
            --noautoconsole                                                                                     \
            --console pty,target_type=serial'''

            run_cmd(create_command)
            run_cmd("ssh-keygen -f " + str(Path.home()) + "/.ssh/known_hosts -R " + item.get("ip"), True)


def wait_for_cm():
    print("Starting and waiting for port 7180 to be available on " + IP_CM + "...")
    while True:
        try:
            with socket.create_connection((IP_CM, 7180), timeout=600):
                break
        except OSError as ex:
            time.sleep(0.01)
    print('')
    print('Done. Run this command to connect:')
    print('')
    print('ssh -o "StrictHostKeyChecking=no" -i work/id_rsa ' + VM_USER_NAME + '@' + IP_CM)


def run_cmd(program, hide_output=False):
    fnull = open(os.devnull, 'w')
    if hide_output:
        process = subprocess.Popen(program, shell=True, stdout=fnull, stderr=subprocess.STDOUT, executable="/bin/bash")
        process.communicate()
    else:
        process = subprocess.Popen(program, shell=True, executable="/bin/bash")
        process.communicate()


# install_requirements()
prepare_config_file()
cleanup()
create_extra_images()
get_os_image()
make_cloudinit_image()
restore_os_image()
create_network()
create_vms()
wait_for_cm()
