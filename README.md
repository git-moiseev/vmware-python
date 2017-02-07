# vmware-python

Based on  https://github.com/vmware/pyvmomi-community-samples.git
Python program for cold migration VMs from/to Virtual Center or ESXi host

## Steps to do

* Edit credentials file .credentials.json
```
{ 
  "host": "vc", 
  "user": "foo", 
  "pwd": "boo", 
  "port": 443
 }
```
* Create portable dump
```
cold-migrate.py --dump --file /tmp/dump.json
```
* Powers off all VMs. If vmware-tools installed and running, shutdowns guests, if not, poweroff
```
cold-migrate.py --poweroff
```
* Remove all VMs from inventory
```
 --unregister
```
* migrate Virtual Center to new location manualy
* change dump.json, if needed (New datasore path, destination folders, etc..)
* Add VMs from dump file to inventory
```
--register
```
* Turn the power on all servers that was poweredOn at the time of the dump
```
--poweron
```

# TODO
If you have distributed switch, after remove machine from inventory,
when you add it back, virtual network adapters will be NOT connected to
any network. This is not a bug, this is the way VmWare works.
