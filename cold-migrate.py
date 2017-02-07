#!/usr/bin/env python
# VMware vSphere Python SDK
# Copyright (c) 2008-2013 VMware, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Based on  https://github.com/vmware/pyvmomi-community-samples.git

Python program for cold migration VMs from/to Virtual Center or ESXi host
Steps to do
1) --dump --file /tmp/dump.json
2) --poweroff
3) --unregister
4) migrate Virtual Center to new location manualy
5) change dump.json, if needed (New datasore path, destination folders, etc..)
6) --register
7) --poweron

TODO
If you have distributed switch, after remove machine from inventory,
when you add it back, virtual network adapters will be NOT connected to
any network. This is not a bug, this is the way VmWare works.

"""

import atexit

from pyVim import connect
from pyVmomi import vmodl
from pyVmomi import vim

import json
import argparse
import sys
import textwrap
from time import sleep


def get_obj(content, vimtype, name):
    """
    Return an object by name, if name is None the
    first found object is returned
    """
    obj = None
    container = content.viewManager.CreateContainerView(
        content.rootFolder, vimtype, True)
    for c in container.view:
        if name:
            if c.name == name:
                obj = c
                break
        else:
            obj = c
            break

    return obj


def vc_content():
    try:
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
        context.verify_mode = ssl.CERT_NONE
        credits = read_data(credits_file)

        service_instance = connect.SmartConnect(host=credits['host'],
                                                user=credits['user'],
                                                pwd=credits['pwd'],
                                                port=credits['port'],
                                                sslContext=context)
        atexit.register(connect.Disconnect, service_instance)

        content = service_instance.RetrieveContent()
        if content:
            msg('DEBUG', "Connected to {}".format(credits['host']))
        return content

    except vmodl.MethodFault as error:
        print("Caught vmodl fault : " + error.msg)
        return -1


def msg(level, text):
    style = {
        'W': '\033[0m',           # white (normal)
        'ERROR':  '\033[31m',     # red
        'INFO': '\033[32m',       # green
        'WARN':    '\033[33m',    # orange
        'BLUE':  '\033[34m',      # dark blue
        'DEBUG':  '\033[36m',     # cyan
        'P': '\033[35m'           # purple
    }
    if level in ['INFO', 'WARN', 'ERROR', 'DEBUG']:
        print "{}{}{}".format(style[level], text, style['W'])
    else:
        print text


def dump_vm_info(vm):
    d = {}
    d['name'] = vm.summary.config.name
    d['path'] = vm.summary.config.vmPathName
    d['folder'] = vm.parent.name
    d['state'] = vm.summary.runtime.powerState
    d['uuid'] = vm.summary.config.instanceUuid
    d['tools'] = vm.summary.guest.toolsStatus
    return d


def dump():
    content = vc_content()
    container = content.rootFolder  # starting point to look into
    viewType = [vim.VirtualMachine]  # object types to look for
    recursive = True  # whether we should look into it recursively
    containerView = content.viewManager.CreateContainerView(
        container, viewType, recursive)
    children = containerView.view
    dump = []
    for child in children:
        if child.summary.config.name not in excluded_vm:
            dump.append(dump_vm_info(child))
    if args.file:
        f = open(filename, 'w')
        f.write(json.dumps(dump, indent=4))
        f.close()
        return "Write dump of {} vm's to {}".format(len(dump), filename)
    else:
        return json.dumps(dump, indent=4)


def read_data(filename):
    try:
        f = open(filename, 'rb')
    except IOError:
        print "Could not read file:", filename
        sys.exit()
    with open(filename) as f:
        data = json.load(f)
    return data


def poweron():
    content = vc_content()
    data = read_data(filename)

    for v in data:
        if v['state'] == "poweredOn":
            vm = content.searchIndex.FindByUuid(None, v['uuid'], True, True)
            msg('INFO', "VM '{:32}': Powers on".format(v['name']))
            task = vm.PowerOn()
            # We track the question ID & answer so we don't end up answering the same
            # questions repeatedly.
            answers = {}
            while task.info.state not in [vim.TaskInfo.State.success,
                                          vim.TaskInfo.State.error]:

                # we'll check for a question, if we find one, handle it,
                # Note: question is an optional attribute and this is how pyVmomi
                # handles optional attributes. They are marked as None.
                if vm.runtime.question is not None:
                    question_id = vm.runtime.question.id
                    if question_id not in answers.keys():
                        #answers[question_id] = answer_vm_question(vm)
                        answers[question_id] = '1'  # button.uuid.movedTheVM
                        vm.AnswerVM(question_id, answers[question_id])

        else:
            msg('WARN', "VM '{:32}': Was powered off. Skip it.".format(
                v['name']))


def answer_vm_question(virtual_machine):
    print "\n"
    choices = virtual_machine.runtime.question.choice.choiceInfo
    for option in choices:
        if option.label == 'button.uuid.movedTheVM':
            return option.key
        # if not button.uuid.movedTheVM in choices - ask user

    default_option = None
    if virtual_machine.runtime.question.choice.defaultIndex is not None:
        ii = virtual_machine.runtime.question.choice.defaultIndex
        default_option = choices[ii]
    choice = None
    while choice not in [o.key for o in choices]:
        print "VM power on is paused by this question:\n\n"
        print "\n".join(textwrap.wrap(
            virtual_machine.runtime.question.text, 60))
        for option in choices:
            print "\t %s: %s " % (option.key, option.label)
        if default_option is not None:
            print "default (%s): %s\n" % (default_option.label,
                                          default_option.key)
        choice = raw_input("\nchoice number: ").strip()
        print "..."
    return choice


def poweroff():
    content = vc_content()
    data = read_data(filename)
    for v in data:
        vm = content.searchIndex.FindByUuid(None, v['uuid'], True, True)
        if vm.summary.runtime.powerState == "poweredOn":
            if vm.summary.guest.toolsStatus not in ["toolsNotInstalled", "toolsNotRunning"]:
                msg('INFO', "VM {:32}: Shutdown Guest".format(v['name']))
                vm.ShutdownGuest()
            else:
                msg('WARN', "VM {:32}: Tools not found. Power off".format(
                    v['name']))
                vm.PowerOff()
        else:
            msg('WARN', "VM {:32}: It is powered off. Skip it.".format(
                v['name']))


def register():
    content = vc_content()
    cluster_name = None
    datacenter_name = None
    resource_pool = None

    # if none git the first one
    if datacenter_name:
        datacenter = get_obj(content, [vim.Datacenter], datacenter_name)
    else:
        datacenter = get_obj(content, [vim.Datacenter], '')

    # if None, get the first one
    if cluster_name:
        cluster = get_obj(content, [vim.ClusterComputeResource], cluster_name)
    else:
        cluster = get_obj(content, [vim.ClusterComputeResource], '')

    if resource_pool:
        resource_pool = get_obj(content, [vim.ResourcePool], resource_pool)
    else:
        resource_pool = cluster.resourcePool

    esxhost = content.searchIndex.FindByDnsName(None, "esx6", vmSearch=False)

    data = read_data(filename)
    for v in data:
        destfolder = get_obj(content, [vim.Folder], v['folder'])
        if destfolder:
            destfolder.RegisterVM_Task(
                v['path'], v['name'], asTemplate=False, pool=resource_pool)
            msg('INFO', "VM '{0:32}': registered in folder '{1}'".format(
                v['name'], v['folder']))
        else:
            msg('WARN', "VM '{0:32}': folder nopt found '{1}'".format(
                v['name'], v['folder']))


def unregister():
    content = vc_content()
    data = read_data(filename)
    for v in data:
        vm = content.searchIndex.FindByUuid(None, v['uuid'], True, True)
        msg('INFO', "VM '{:32}': Unregistered".format(v['name']))
        vm.UnregisterVM()

# Start program
if __name__ == "__main__":

    # login credentials file. Example: '{"host": "vc", "user": "foo", "pwd":
    # "boo", "port":443}'
    credits_file = '/home/captain/.vsphere.json'
    # Do not do anything with vm with names in list. Migrate them manualy
    excluded_vm = ['VMware vCenter Server 5.5']
    filename = args.file

    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument(
        '--dump', help='Dump all VM to file', action="store_true")
    parser.add_argument('--file', help='Filename with dump',
                        default='/tmp/dump.json')
    parser.add_argument(
        '--unregister', help='unregister VM from file', action="store_true")
    parser.add_argument(
        '--register', help='register VM from file', action="store_true")
    parser.add_argument(
        '--poweroff', help='poweroff all VM from file', action="store_true")
    parser.add_argument(
        '--poweron', help='power on all VM from file', action="store_true")
    # parser.add_argument(
    #     '--suspend', help='suspend all VM from file', action="store_true")

    args = parser.parse_args()

    if args.register:
        register()
    if args.unregister:
        unregister()
    if args.poweron:
        poweron()
    if args.poweroff:
        poweroff()
    if args.dump:
        print dump()
