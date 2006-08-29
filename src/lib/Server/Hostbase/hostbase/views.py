# Create your views here.
"""Views.py
Contains all the views associated with the hostbase app
Also has does form validation
"""
__revision__ = 0.1

from django.http import HttpResponse, HttpResponseRedirect
from models import *
from Cheetah.Template import Template
from datetime import date
from django.db import connection
import re

attribs = ['hostname', 'whatami', 'netgroup', 'security_class', 'support',
           'csi', 'printq', 'primary_user', 'administrator', 'location',
           'comments', 'status']

dispatch = {'mac_addr':'i.mac_addr LIKE \'%%%%%s%%%%\'',
            'ip_addr':'p.ip_addr LIKE \'%%%%%s%%%%\'',
            'name':'n.name LIKE \'%%%%%s%%%%\'',
            'cname':'c.cname LIKE \'%%%%%s%%%%\'',
            'mx':'m.mx LIKE \'%%%%%s%%%%\'',
            'dns_view':'n.dns_view = \'%s\'',
            'hdwr_type':'i.hdwr_type = \'%s\''}


## def netreg(request):
##     if request.GET.has_key('sub'):
##         failures = []
##         validated = True
##         # do validation right in here
##         macaddr_regex = re.compile('^[0-9abcdef]{2}(:[0-9abcdef]{2}){5}$')
##         if not (request.POST['mac_addr'] and macaddr_regex.match(request.POST['mac_addr'])):
##             validated = False
##         userregex = re.compile('^[a-z0-9-_\.@]+$')
##         if not (request.POST['email_address'] and userregex.match(request.POST['email_address'])):
##             validated = False
##         if not validated:
##             t = Template(open('./hostbase/webtemplates/errors.html').read())
##             t.failures = validate(request, True)
##             return HttpResponse(str(t))
##         return HttpResponseRedirect('/hostbase/%s/' % host.id)
##     else:
##         t = Template(open('./hostbase/webtemplates/netreg.html').read())
##         t.TYPE_CHOICES = Interface.TYPE_CHOICES
##         t.failures = False
##         return HttpResponse(str(t))
    

def search(request):
    """Search for hosts in the database
    If more than one field is entered, logical AND is used
    """
    if request.GET.has_key('sub'):
        querystring = """SELECT DISTINCT h.hostname, h.id, h.status
        FROM (((((hostbase_host h
        INNER JOIN hostbase_interface i ON h.id = i.host_id)
        INNER JOIN hostbase_ip p ON i.id = p.interface_id)
        INNER JOIN hostbase_name n ON p.id = n.ip_id)
        INNER JOIN hostbase_name_mxs x ON n.id = x.name_id)
        INNER JOIN hostbase_mx m ON m.id = x.mx_id)
        LEFT JOIN hostbase_cname c ON n.id = c.name_id
        WHERE """

        _and = False
        for field in request.POST:
            if request.POST[field] and field in dispatch:
                if _and:
                    querystring += ' AND '
                querystring += dispatch[field]  % request.POST[field]
                _and = True
            elif request.POST[field]:
                if _and:
                    querystring += ' AND '
                querystring += "h.%s LIKE \'%%%%%s%%%%\'" % (field, request.POST[field])
                _and = True

                
        if not _and:
            cursor = connection.cursor()
            cursor.execute("""SELECT hostname, id, status
            FROM hostbase_host ORDER BY hostname""")
            results = cursor.fetchall()
        else:
            querystring += " ORDER BY h.hostname"
            cursor = connection.cursor()
            cursor.execute(querystring)
            results = cursor.fetchall()
        
        temp = Template(open('./hostbase/webtemplates/results.html').read())
        temp.hosts = results
        return HttpResponse(str(temp))
    else:
        temp = Template(open('./hostbase/webtemplates/search.html').read())
        temp.TYPE_CHOICES = Interface.TYPE_CHOICES
        temp.DNS_CHOICES = Name.DNS_CHOICES
        temp.yesno = [(1, 'yes'), (0, 'no')]
        return HttpResponse(str(temp))

def look(request, host_id):
    """Displays general host information"""
    temp = Template(open('./hostbase/webtemplates/host.html').read())
    hostdata = gethostdata(host_id)
    temp = fill(temp, hostdata)
    return HttpResponse(str(temp))
    
def dns(request, host_id):
    temp = Template(open('./hostbase/webtemplates/dns.html').read())
    hostdata = gethostdata(host_id, True)
    temp = fill(temp, hostdata, True)
    return HttpResponse(str(temp))

def edit(request, host_id):
    """Edit general host information
    Data is validated before being committed to the database"""
    # fix bug when ip address changes, update the dns info appropriately

    if request.GET.has_key('sub'):
        host = Host.objects.get(id=host_id)
        interfaces = host.interface_set.all()
        if not validate(request, False, host_id):
            if (request.POST.has_key('outbound_smtp')
                and not host.outbound_smtp or
                not request.POST.has_key('outbound_smtp')
                and host.outbound_smtp):
                host.outbound_smtp = not host.outbound_smtp
            if (request.POST.has_key('dhcp') and not host.dhcp or
                not request.POST.has_key('dhcp') and host.dhcp):
                host.dhcp = not host.dhcp
            # add validation for attribs here
            # likely use a helper fucntion
            for attrib in attribs:
                if request.POST.has_key(attrib):
                    host.__dict__[attrib] = request.POST[attrib]
            if len(request.POST['expiration_date'].split("-")) == 3:
                (year, month, day) = request.POST['expiration_date'].split("-")
                host.expiration_date = date(int(year), int(month), int(day))
            for inter in interfaces:
                ips = IP.objects.filter(interface=inter.id)
                inter.mac_addr = request.POST['mac_addr%d' % inter.id]
                oldtype = inter.hdwr_type
                inter.hdwr_type = request.POST['hdwr_type%d' % inter.id]
                oldname = "-".join([host.hostname.split(".", 1)[0], oldtype])
                oldname += "." + host.hostname.split(".", 1)[1]
                newname = "-".join([host.hostname.split(".", 1)[0],
                                    inter.hdwr_type])
                newname += "." + host.hostname.split(".", 1)[1]
                for name in Name.objects.filter(name=oldname):
                    name.name = newname
                    name.save()
                for ip in ips:
                    oldip = ip.ip_addr
                    ip.ip_addr = request.POST['ip_addr%d' % ip.id]
                    ip.save()
                    oldname = "-".join([host.hostname.split(".", 1)[0],
                                        oldip.split(".")[2]])
                    oldname += "." + host.hostname.split(".", 1)[1]
                    newname = "-".join([host.hostname.split(".", 1)[0],
                                        ip.ip_addr.split(".")[2]])
                    newname += "." + host.hostname.split(".", 1)[1]
                    if Name.objects.filter(name=oldname):
                        name = Name.objects.get(name=oldname, ip=ip.id)
                        name.name = newname
                        name.save()
                if request.POST['%dip_addr' % inter.id]:
                    mx, created = MX.objects.get_or_create(priority=30, mx='mailgw.mcs.anl.gov')
                    if created:
                        mx.save()
                    new_ip = IP(interface=inter, num=len(ips),
                                ip_addr=request.POST['%dip_addr' % inter.id])
                    new_ip.save()
                    new_name = "-".join([host.hostname.split(".")[0],
                                         new_ip.ip_addr.split(".")[2]])
                    new_name += "." + host.hostname.split(".", 1)[1]
                    name = Name(ip=new_ip, name=new_name,
                                dns_view='global', only=False)
                    name.save()
                    name.mxs.add(mx)
                    new_name = "-".join([host.hostname.split(".")[0],
                                         inter.hdwr_type])
                    new_name += "." + host.hostname.split(".", 1)[1]
                    name = Name(ip=new_ip, name=new_name,
                                dns_view='global', only=False)
                    name.save()
                    name.mxs.add(mx)
                    name = Name(ip=new_ip, name=host.hostname,
                                dns_view='global', only=False)
                    name.save()
                    name.mxs.add(mx)
                inter.save()
            if request.POST['mac_addr_new']:
                new_inter = Interface(host=host,
                                      mac_addr=request.POST['mac_addr_new'],
                                      hdwr_type=request.POST['hdwr_type_new'])
                new_inter.save()
            if request.POST['mac_addr_new'] and request.POST['ip_addr_new']:
                mx, created = MX.objects.get_or_create(priority=30, mx='mailgw.mcs.anl.gov')
                if created:
                    mx.save()
                new_ip = IP(interface=new_inter, num=0,
                            ip_addr=request.POST['ip_addr_new'])
                new_ip.save()
                new_name = "-".join([host.hostname.split(".")[0],
                                     new_ip.ip_addr.split(".")[2]])
                new_name += "." + host.hostname.split(".", 1)[1]
                name = Name(ip=new_ip, name=new_name,
                            dns_view='global', only=False)
                name.save()
                name.mxs.add(mx)
                new_name = "-".join([host.hostname.split(".")[0],
                                     new_inter.hdwr_type])
                new_name += "." + host.hostname.split(".", 1)[1]
                name = Name(ip=new_ip, name=new_name,
                            dns_view='global', only=False)
                name.save()
                name.mxs.add(mx)
                name = Name(ip=new_ip, name=host.hostname,
                            dns_view='global', only=False)
                name.save()
                name.mxs.add(mx)
            if request.POST['ip_addr_new'] and not request.POST['mac_addr_new']:
                mx, created = MX.objects.get_or_create(priority=30, mx='mailgw.mcs.anl.gov')
                if created:
                    mx.save()
                new_inter = Interface(host=host, mac_addr="",
                                      hdwr_type=request.POST['hdwr_type_new'])
                new_inter.save()
                new_ip = IP(interface=new_inter, num=0,
                            ip_addr=request.POST['ip_addr_new'])
                new_ip.save()
                new_name = "-".join([host.hostname.split(".")[0],
                                     new_ip.ip_addr.split(".")[2]])
                new_name += "." + host.hostname.split(".", 1)[1]
                name = Name(ip=new_ip, name=new_name,
                            dns_view='global', only=False)
                name.save()
                new_name = "-".join([host.hostname.split(".")[0],
                                     new_inter.hdwr_type])
                new_name += "." + host.hostname.split(".", 1)[1]
                name = Name(ip=new_ip, name=new_name,
                            dns_view='global', only=False)
                name.save()
                name = Name(ip=new_ip, name=host.hostname,
                            dns_view='global', only=False)
                name.save()
            host.save()
            return HttpResponseRedirect('/hostbase/%s/' % host.id)
        else:
            t = Template(open('./hostbase/webtemplates/errors.html').read())
            t.failures = validate(request, False, host_id)
            return HttpResponse(str(t))
        # examine the check boxes for any changes
    else:
        t = Template(open('./hostbase/webtemplates/edit.html').read())
        hostdata = gethostdata(host_id)
        t = fill(t, hostdata)
        t.type_choices = Interface.TYPE_CHOICES
        t.request = request
        return HttpResponse(str(t))

def confirm(request, item, item_id, host_id, name_id=None):
    """Asks if the user is sure he/she wants to remove an item"""
    if request.GET.has_key('sub'):
        if item == 'interface':
            for ip in Interface.objects.get(id=item_id).ip_set.all():
                for name in ip.name_set.all():
                    name.cname_set.all().delete()
                ip.name_set.all().delete()
            Interface.objects.get(id=item_id).ip_set.all().delete()
            Interface.objects.get(id=item_id).delete()
        elif item=='ip':
            for name in IP.objects.get(id=item_id).name_set.all():
                name.cname_set.all().delete()
            IP.objects.get(id=item_id).name_set.all().delete()
            IP.objects.get(id=item_id).delete()
        elif item=='cname':
            CName.objects.get(id=item_id).delete()
        elif item=='mx':
            mx = MX.objects.get(id=item_id)
            Name.objects.get(id=name_id).mxs.remove(mx)
        elif item=='name':
            Name.objects.get(id=item_id).cname_set.all().delete()
            Name.objects.get(id=item_id).delete()
        if item == 'cname' or item == 'mx' or item == 'name':
            return HttpResponseRedirect('/hostbase/%s/dns' % host_id)
        else:
            return HttpResponseRedirect('/hostbase/%s/edit' % host_id)
    else:
        temp = Template(open('./hostbase/webtemplates/confirm.html').read())
        interface = None
        ips = []
        names = {}
        cnames = {}
        mxs = {}
        if item == 'interface':
            interface = Interface.objects.get(id=item_id)
            ips = interface.ip_set.all()
            for ip in ips:
                names[ip.id] = ip.name_set.all()
                for name in names[ip.id]:
                    cnames[name.id] = name.cname_set.all()
                    mxs[name.id] = name.mx_set.all()
        elif item=='ip':
            ips = [IP.objects.get(id=item_id)]
            names[ips[0].id] = ips[0].name_set.all()
            for name in names[ips[0].id]:
                cnames[name.id] = name.cname_set.all()
                mxs[name.id] = name.mx_set.all()
        elif item=='name':
            names = [Name.objects.get(id=item_id)]
            for name in names:
                cnames[name.id] = name.cname_set.all()
                mxs[name.id] = name.mxs.all()
        elif item=='cname':
            cnames = [CName.objects.get(id=item_id)]
        elif item=='mx':
            mxs = [MX.objects.get(id=item_id)]
        temp.interface = interface
        temp.ips = ips
        temp.names = names
        temp.cnames = cnames
        temp.mxs = mxs
        temp.id = item_id
        temp.type = item
        temp.host_id = host_id
        return HttpResponse(str(temp))

def dnsedit(request, host_id):
    """Edits specific DNS information
    Data is validated before committed to the database"""
    if request.GET.has_key('sub'):
        hostdata = gethostdata(host_id, True)
        for ip in hostdata['names']:
            ipaddr = IP.objects.get(id=ip)
            ipaddrstr = ipaddr.__str__()
            for name in hostdata['cnames']:
                for cname in hostdata['cnames'][name]:
                    cname.cname = request.POST['cname%d' % cname.id]
                    cname.save()
            for name in hostdata['mxs']:
                for mx in hostdata['mxs'][name]:
                    mx.priority = request.POST['priority%d' % mx.id]
                    mx.mx = request.POST['mx%d' % mx.id]
                    mx.save()
            for name in hostdata['names'][ip]:
                name.name = request.POST['name%d' % name.id]
                if request.POST['%dcname' % name.id]:
                    cname = CName(name=name,
                                  cname=request.POST['%dcname' % name.id])
                    cname.save()
                if (request.POST['%dpriority' % name.id] and
                    request.POST['%dmx' % name.id]):
                    mx, created = MX.objects.get_or_create(priority=request.POST['%dpriority' % name.id],
                            mx=request.POST['%dmx' % name.id])
                    if created:
                        mx.save()
                    name.mxs.add(mx)
                name.save()
            if request.POST['%sname' % ipaddrstr]:
                name = Name(ip=ipaddr,
                            dns_view=request.POST['%sdns_view' % ipaddrstr],
                            name=request.POST['%sname' % ipaddrstr], only=False)
                name.save()
                if request.POST['%scname' % ipaddrstr]:
                    cname = CName(name=name,
                                  cname=request.POST['%scname' % ipaddrstr])
                    cname.save()
                if (request.POST['%smx' % ipaddrstr] and
                    request.POST['%spriority' % ipaddrstr]):
                    mx, created = MX.objects.get_or_create(priority=request.POST['%spriority' % ipaddrstr],
                            mx=request.POST['%smx' % ipaddrstr])
                    if created:
                        mx.save()
                    name.mxs.add(mx)
        return HttpResponseRedirect('/hostbase/%s/dns' % host_id)
    else:
        temp = Template(open('./hostbase/webtemplates/dnsedit.html').read())
        hostdata = gethostdata(host_id, True)
        temp = fill(temp, hostdata, True)
        temp.request = request
        return HttpResponse(str(temp))

def gethostdata(host_id, dnsdata=False):
    """Grabs the necessary data about a host
    Replaces a lot of repeated code"""
    hostdata = {}
    hostdata['ips'] = {}
    hostdata['names'] = {}
    hostdata['cnames'] = {}
    hostdata['mxs'] = {}
    hostdata['host'] = Host.objects.get(id=host_id)
    hostdata['interfaces'] = hostdata['host'].interface_set.all()
    for interface in hostdata['interfaces']:
        hostdata['ips'][interface.id] = interface.ip_set.all()
        if dnsdata:
            for ip in hostdata['ips'][interface.id]:
                hostdata['names'][ip.id] = ip.name_set.all()
                for name in hostdata['names'][ip.id]:
                    hostdata['cnames'][name.id] = name.cname_set.all()
                    hostdata['mxs'][name.id] = name.mxs.all()
    return hostdata

def fill(template, hostdata, dnsdata=False):
    """Fills a generic template
    Replaces a lot of repeated code"""
    if dnsdata:
        template.names = hostdata['names']
        template.cnames = hostdata['cnames']
        template.mxs = hostdata['mxs']
    template.host = hostdata['host']
    template.interfaces = hostdata['interfaces']
    template.ips = hostdata['ips']
    return template

    
def new(request):
    """Function for creating a new host in hostbase
    Data is validated before committed to the database"""
    if request.GET.has_key('sub'):
        if not validate(request, True):
            host = Host()
            # this is the stuff that validate() should take care of
            # examine the check boxes for any changes
            host.outbound_smtp = request.POST.has_key('outbound_smtp')
            host.dhcp = request.POST.has_key('dhcp')
            for attrib in attribs:
                if request.POST.has_key(attrib):
                    host.__dict__[attrib] = request.POST[attrib]
            host.status = 'active'
            host.save()
        else:
            temp = Template(open('./hostbase/webtemplates/errors.html').read())
            temp.failures = validate(request, True)
            return HttpResponse(str(temp))
        if request.POST['mac_addr_new']:
            new_inter = Interface(host=host,
                                  mac_addr=request.POST['mac_addr_new'],
                                  hdwr_type=request.POST['hdwr_type_new'])
            new_inter.save()
        if request.POST['mac_addr_new'] and request.POST['ip_addr_new']:
            new_ip = IP(interface=new_inter,
                        num=0, ip_addr=request.POST['ip_addr_new'])
            new_ip.save()
            new_name = "-".join([host.hostname.split(".")[0],
                                 new_ip.ip_addr.split(".")[2]])
            new_name += "." + host.hostname.split(".", 1)[1]
            name = Name(ip=new_ip, name=new_name, dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()
            new_name = "-".join([host.hostname.split(".")[0],
                                 new_inter.hdwr_type])
            new_name += "." + host.hostname.split(".", 1)[1]
            name = Name(ip=new_ip, name=new_name,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()
            name = Name(ip=new_ip, name=host.hostname,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()            
        if request.POST['ip_addr_new1'] and not request.POST['mac_addr_new1']:
            new_inter = Interface(host=host,
                                  mac_addr="",
                                  hdwr_type=request.POST['hdwr_type_new1'])
            new_inter.save()
            new_ip = IP(interface=new_inter, num=0,
                        ip_addr=request.POST['ip_addr_new1'])
            new_ip.save()
            new_name = "-".join([host.hostname.split(".")[0],
                                 new_ip.ip_addr.split(".")[2]])
            new_name += "." + host.hostname.split(".", 1)[1]
            name = Name(ip=new_ip, name=new_name,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()
            new_name = "-".join([host.hostname.split(".")[0],
                                 new_inter.hdwr_type])
            new_name += "." + host.hostname.split(".", 1)[1]
            name = Name(ip=new_ip, name=new_name,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()
            name = Name(ip=new_ip, name=host.hostname,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()            
        if request.POST['mac_addr_new2']:
            new_inter = Interface(host=host,
                                  mac_addr=request.POST['mac_addr_new2'],
                                  hdwr_type=request.POST['hdwr_addr_new2'])
            new_inter.save()
        if request.POST['mac_addr_new2'] and request.POST['ip_addr_new2']:
            new_ip = IP(interface=new_inter, num=0,
                        ip_addr=request.POST['ip_addr_new2'])
            new_ip.save()
            new_name = "-".join([host.hostname.split(".")[0],
                                 new_ip.ip_addr.split(".")[2]])
            new_name += "." + host.hostname.split(".", 1)[1]
            name = Name(ip=new_ip, name=new_name,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()
            new_name = "-".join([host.hostname.split(".")[0],
                                 new_inter.hdwr_type])
            new_name += "." + host.hostname.split(".", 1)[1]
            name = Name(ip=new_ip, name=new_name,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()
            name = Name(ip=new_ip, name=host.hostname,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()            
        if request.POST['ip_addr_new2'] and not request.POST['mac_addr_new2']:
            new_inter = Interface(host=host,
                                  mac_addr="",
                                  hdwr_type=request.POST['hdwr_type_new2'])
            new_inter.save()
            new_ip = IP(interface=new_inter, num=0,
                        ip_addr=request.POST['ip_addr_new2'])
            new_ip.save()
            new_name = "-".join([host.hostname.split(".")[0],
                                 new_ip.ip_addr.split(".")[2]])
            new_name += "." + host.hostname.split(".", 1)[1]
            name = Name(ip=new_ip, name=new_name,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()
            new_name = "-".join([host.hostname.split(".")[0],
                                 new_inter.hdwr_type])
            new_name += "." + host.hostname.split(".", 1)[1]
            name = Name(ip=new_ip, name=new_name,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()
            name = Name(ip=new_ip, name=host.hostname,
                        dns_view='global', only=False)
            name.save()
            mx = MX(name=name, priority=30, mx='mailgw.mcs.anl.gov')
            mx.save()            
        host.save()
        return HttpResponseRedirect('/hostbase/%s/' % host.id)
    else:
        temp = Template(open('./hostbase/webtemplates/new.html').read())
        temp.TYPE_CHOICES = Interface.TYPE_CHOICES
        temp.NETGROUP_CHOICES = Host.NETGROUP_CHOICES
        temp.CLASS_CHOICES = Host.CLASS_CHOICES
        temp.SUPPORT_CHOICES = Host.SUPPORT_CHOICES
        temp.failures = False
        return HttpResponse(str(temp))
    
def validate(request, new=False, host_id=None):
    """Function for checking form data"""
    failures = []
    dateregex = re.compile('^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    if (request.POST['expiration_date']
        and dateregex.match(request.POST['expiration_date'])):
        try:
            (year, month, day) = request.POST['expiration_date'].split("-")
            date(int(year), int(month), int(day))
        except (ValueError):
            failures.append('expiration_date')
    elif request.POST['expiration_date']:
        failures.append('expiration_date')

    hostregex = re.compile('^[a-z0-9-_]+(\.[a-z0-9-_]+)+$')
    if not (request.POST['hostname']
            and hostregex.match(request.POST['hostname'])):
        failures.append('hostname')

    printregex = re.compile('^[a-z0-9-]+$')
    if not printregex.match(request.POST['printq']) and request.POST['printq']:
        failures.append('printq')

    userregex = re.compile('^[a-z0-9-_\.@]+$')
    if not userregex.match(request.POST['primary_user']):
        failures.append('primary_user')

    if (not userregex.match(request.POST['administrator'])
        and request.POST['administrator']):
        failures.append('administrator')

    locationregex = re.compile('^[0-9]{3}-[a-z][0-9]{3}$|none|bmr|cave|dsl|evl|mobile|offsite|mural|activespaces')
    if not (request.POST['location']
            and locationregex.match(request.POST['location'])):
        failures.append('location')

    if new:
        macaddr_regex = re.compile('^[0-9abcdef]{2}(:[0-9abcdef]{2}){5}$')
        if (not macaddr_regex.match(request.POST['mac_addr_new'])
            and request.POST['mac_addr_new']):
            failures.append('mac_addr (#1)')
        if ((request.POST['mac_addr_new'] or request.POST['ip_addr_new']) and
            not request.has_key('hdwr_type_new')):
            failures.append('hdwr_type (#1)')
        if ((request.POST['mac_addr_new2'] or request.POST['ip_addr_new']) and
            not request.has_key('hdwr_type_new2')):
            failures.append('hdwr_type (#2)')

        if (not macaddr_regex.match(request.POST['mac_addr_new2'])
            and request.POST['mac_addr_new2']):
            failures.append('mac_addr (#2)')

        ipaddr_regex = re.compile('^[0-9]{1,3}(\.[0-9]{1,3}){3}$')
        if (not ipaddr_regex.match(request.POST['ip_addr_new'])
            and request.POST['ip_addr_new']):
            failures.append('ip_addr (#1)')
        if (not ipaddr_regex.match(request.POST['ip_addr_new2'])
            and request.POST['ip_addr_new2']):
            failures.append('ip_addr (#2)')

        [failures.append('ip_addr (#1)') for number in
         request.POST['ip_addr_new'].split(".")
         if number.isdigit() and int(number) > 255
         and 'ip_addr (#1)' not in failures]
        [failures.append('ip_addr (#2)') for number in
         request.POST['ip_addr_new2'].split(".")
         if number.isdigit() and int(number) > 255
         and 'ip_addr (#2)' not in failures]

    elif host_id:
        macaddr_regex = re.compile('^[0-9abcdef]{2}(:[0-9abcdef]{2}){5}$')
        ipaddr_regex = re.compile('^[0-9]{1,3}(\.[0-9]{1,3}){3}$')
        interfaces = Interface.objects.filter(host=host_id)
        for interface in interfaces:
            if (not macaddr_regex.match(request.POST['mac_addr%d' % interface.id])
                and request.POST['mac_addr%d' % interface.id]):
                failures.append('mac_addr (%s)' % request.POST['mac_addr%d' % interface.id])
            for ip in interface.ip_set.all():
                if not ipaddr_regex.match(request.POST['ip_addr%d' % ip.id]):
                    failures.append('ip_addr (%s)' % request.POST['ip_addr%d' % ip.id])
                [failures.append('ip_addr (%s)' % request.POST['ip_addr%d' % ip.id])
                 for number in request.POST['ip_addr%d' % ip.id].split(".")
                 if (number.isdigit() and int(number) > 255 and
                     'ip_addr (%s)' % request.POST['ip_addr%d' % ip.id] not in failures)]

        


    if not failures:
        return 0
    return failures