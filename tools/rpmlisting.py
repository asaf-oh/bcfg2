#!/usr/bin/python -u

import os
import sys
import commands
import getopt
import re


def run_or_die(command):
    (status, stdio) = commands.getstatusoutput(command)
    if status != 0:
        raise Exception("command '%s' failed with exit status %d and output '%s'" %
                        (command, status, stdio))
    return stdio


def rpmblob_cmp(a, b):
    """cmp() implementation for rpmblobs, suitable for use with sort()."""
    ret = cmp(a['name'], b['name'])
    if ret == 0:
        ret = verstr_cmp(a['version'], b['version'])
        if ret == 0:
            ret = verstr_cmp(a['release'], b['release'])
    return ret


def verstr_cmp(a, b):
    """cmp() implementation for version strings, suitable for use with sort()."""
    ret = 0
    index = 0
    a_parts = subdivide(a)
    b_parts = subdivide(b)
    prerelease_pattern = re.compile('rc|pre')
    while ret == 0 and index < min(len(a_parts), len(b_parts)):
        subindex = 0
        a_subparts = a_parts[index]
        b_subparts = b_parts[index]
        while ret == 0 and subindex < min(len(a_subparts), len(b_subparts)):
            ret = cmp(a_subparts[subindex], b_subparts[subindex])
            if ret != 0:
                return ret
            subindex = subindex + 1
        if len(a_subparts) != len(b_subparts):
            # handle prerelease special case at subpart level (ie, '4.0.2rc5').
            if len(a_subparts) > len(b_subparts) and prerelease_pattern.match(str(a_subparts[subindex])):
                return -1
            elif len(a_subparts) < len(b_subparts) and prerelease_pattern.match(str(b_subparts[subindex])):
                return 1
            else:
                return len(a_subparts) - len(b_subparts)
        index = index + 1
    if len(a_parts) != len(b_parts):
        # handle prerelease special case at part level (ie, '4.0.2.rc5).
        if len(a_parts) > len(b_parts) and prerelease_pattern.match(str(a_parts[index][0])):
            return -1
        elif len(a_parts) < len(b_parts) and prerelease_pattern.match(str(b_parts[index][0])):
            return 1
        else:
            return len(a_parts) - len(b_parts)
    return ret
        

        
def subdivide(verstr):
    """subdivide takes a version or release string and attempts to subdivide it into components to facilitate sorting.  The string is divided into a two level hierarchy of sub-parts.  The upper level is subdivided by periods, and the lower level is subdivided by boundaries between digit, alpha, and other character groupings."""
    parts = []
    # parts is a list of lists representing the subsections which make up a version string.
    # example:
    # 4.0.2b3 would be represented as [[4],[0],[2,'b',3]].
    major_parts = verstr.split('.')
    for major_part in major_parts:
        minor_parts = []
        index = 0
        while index < len(major_part):
            # handle digit subsection
            if major_part[index].isdigit():
                digit_str_part = ""
                while index < len(major_part) and major_part[index].isdigit():
                    digit_str_part = digit_str_part + major_part[index]
                    index = index + 1
                digit_part = int(digit_str_part)
                minor_parts.append(digit_part)
            # handle alpha subsection
            elif major_part[index].isalpha():
                alpha_part = ""
                while index < len(major_part) and major_part[index].isalpha():
                    alpha_part = alpha_part + major_part[index]
                    index = index + 1
                minor_parts.append(alpha_part)
            # handle other characters.  this should only be '_', but we will treat is as a subsection to keep it general.
            elif not major_part[index].isalnum():
                other_part = ""
                while index < len(major_part) and not major_part[index].isalnum():
                    other_part = other_part + major_part[index]
                    index = index + 1
                minor_parts.append(other_part)
            parts.append(minor_parts)
    return parts


def get_pkgs(rpmdir):
    """scan a dir of rpms and generate a pkgs structure."""
    pkgs = {}
    """
pkgs structure:
* pkgs is a dict of package name, rpmblob list pairs:
  pkgs = {name:[rpmblob,rpmblob...], name:[rpmblob,rpmblob...]}
* rpmblob is a dict describing an rpm file:
  rpmblob = {'file':'foo-0.1-5.i386.rpm', 'name':'foo', 'version':'0.1', 'release':'5', 'arch':'i386'},

example:
pkgs = {
'foo' : [
  {'file':'foo-0.1-5.i386.rpm', 'name':'foo', 'version':'0.1', 'release':'5', 'arch':'i386'},
  {'file':'foo-0.2-3.i386.rpm', 'name':'foo', 'version':'0.2', 'release':'3', 'arch':'i386'}],
'bar' : [
  {'file':'bar-3.2a-12.mips.rpm', 'name':'bar', 'version':'3.2a', 'release':'12', 'arch':'mips'},
  {'file':'bar-3.7j-4.mips.rpm', 'name':'bar', 'version':'3.7j', 'release':'4', 'arch':'mips'}]
}
"""
    rpms = [item for item in os.listdir(rpmdir) if item.endswith('.rpm')]
    for rpm in rpms:
        cmd = 'rpm --nosignature --queryformat \'%%{NAME} %%{VERSION} %%{RELEASE} %%{ARCH}\' -q -p %s/%s' % (rpmdir, rpm)
        output = run_or_die(cmd)
        try:
            (name, version, release, arch) = output.split()
        except:
            print "cmd:", cmd
            print "output:", output
            raise
        rpmblob = {'file':rpm, 'name':name, 'version':version, 'release':release, 'arch':arch}
        if pkgs.has_key(name):
            pkgs[name].append(rpmblob)
        else:
            pkgs[name] = [rpmblob]
    return pkgs


def prune_pkgs(pkgs):
    """prune a pkgs structure to contain only the latest version of each package (includes multiarch results)."""
    latest_pkgs = {}
    for rpmblobs in pkgs.values():
        (major, minor) = sys.version_info[:2]
        if major >= 2 and minor >= 4:
            rpmblobs.sort(rpmblob_cmp, reverse=True)
        else:
            rpmblobs.sort(rpmblob_cmp)
            rpmblobs.reverse()
        pkg_name = rpmblobs[0]['name']
        all_archs = [blob for blob in rpmblobs if blob['version'] == rpmblobs[0]['version'] and 
                                                  blob['release'] == rpmblobs[0]['release']]
        latest_pkgs[pkg_name] = all_archs
    return latest_pkgs


def prune_archs(pkgs):
    """prune a pkgs structure to contain no more than one subarch per architecture for each set of packages."""
    subarch_mapping = {'x86':['i686','i586','i386'], 'x86_64':['x86_64'], 'noarch':['noarch']}
    arch_mapping = {'i686':'x86', 'i586':'x86', 'i386':'x86', 'x86_64':'x86_64', 'noarch':'noarch'}
    pruned_pkgs = {}
    for rpmblobs in pkgs.values():
        pkg_name = rpmblobs[0]['name']
        arch_sifter = {}
        for challenger in rpmblobs:
            arch = arch_mapping[challenger['arch']]
            incumbent = arch_sifter.get(arch)
            if incumbent == None:
                arch_sifter[arch] = challenger
            else:
                subarchs = subarch_mapping[arch]
                challenger_index = subarchs.index(challenger['arch'])
                incumbent_index = subarchs.index(incumbent['arch'])
                if challenger_index < incumbent_index:
                    arch_sifter[arch] = challenger
        pruned_pkgs[pkg_name] = arch_sifter.values()
    return pruned_pkgs


def scan_rpm_dir(rpmdir, uri, group, priority=0, output=sys.stdout):
    """the meat of this library."""
    output.write('<PackageList uri="%s" type="rpm" priority="%s">\n' % (uri, priority))
    output.write(' <Group name="%s">\n' % group)
    pkgs = prune_archs(prune_pkgs(get_pkgs(rpmdir)))
    for rpmblobs in pkgs.values():
        if len(rpmblobs) == 1:
            # regular pkgmgr entry
            rpmblob = rpmblobs[0]
            output.write('  <Package name="%s" simplefile="%s" version="%s-%s"/>\n' %
                         (rpmblob['name'], rpmblob['file'], rpmblob['version'], rpmblob['release']))
        else:
            # multiarch pkgmgr entry
            rpmblob = rpmblobs[0]
            archs = [blob['arch'] for blob in rpmblobs]
            archs.sort()
            multiarch_string = ' '.join(archs)
            pattern_string = '\.(%s)\.rpm$' % '|'.join(archs) # e.g., '\.(i386|x86_64)\.rpm$'
            pattern = re.compile(pattern_string)
            multiarch_file = pattern.sub('.%(arch)s.rpm', rpmblob['file']) # e.g., 'foo-1.0-1.%(arch)s.rpm'
            output.write('  <Package name="%s" file="%s" version="%s-%s" multiarch="%s"/>\n' %
                         (rpmblob['name'], multiarch_file, rpmblob['version'], rpmblob['release'], multiarch_string))
    output.write(' </Group>\n')
    output.write('</PackageList>\n')


def usage(output=sys.stdout):
    output.write("Usage: %s [-g <groupname>] [-u <uri>] [-d <dir>] [-p <priority>] [-o <output>]\n" % sys.argv[0])


if __name__ == "__main__":
    try:
        opts, args = getopt.getopt(sys.argv[1:], "g:u:d:p:o:",
                                   ["group=", "uir=", "dir=", "priority=", "output="])
    except getopt.GetoptError:
        usage(sys.stderr)
        sys.exit(1)

    group = "base"
    uri = "http://localhost/rpms"
    rpmdir = "."
    priority = "0"
    output = None

    for opt, arg in opts:
        if opt in ['-g', '--group']:
            group = arg
        elif opt in ['-u', '--uri']:
            uri = arg
        elif opt in ['-d', '--dir']:
            rpmdir = arg
        elif opt in ['-p', '--priority']:
            priority = arg
        elif opt in ['-o', '--output']:
            output = arg

    if output == None:
        output = sys.stdout
    else:
        output = file(output,"w")

    scan_rpm_dir(rpmdir, uri, group, priority, output)