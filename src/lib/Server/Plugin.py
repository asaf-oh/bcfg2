"""This module provides the baseclass for Bcfg2 Server Plugins."""
__revision__ = '$Revision$'

import copy
import logging
import lxml.etree
import os
import pickle
import posixpath
import re
import Queue
import threading

from lxml.etree import XML, XMLSyntaxError

import Bcfg2.Options

# grab default metadata info from bcfg2.conf
opts = {'owner': Bcfg2.Options.MDATA_OWNER,
        'group': Bcfg2.Options.MDATA_GROUP,
        'important': Bcfg2.Options.MDATA_IMPORTANT,
        'perms': Bcfg2.Options.MDATA_PERMS,
        'paranoid': Bcfg2.Options.MDATA_PARANOID}
mdata_setup = Bcfg2.Options.OptionParser(opts)
mdata_setup.parse([])
del mdata_setup['args']

logger = logging.getLogger('Bcfg2.Plugin')

default_file_metadata = mdata_setup

info_regex = re.compile( \
    'encoding:(\s)*(?P<encoding>\w+)|' +
    'group:(\s)*(?P<group>\S+)|' +
    'important:(\s)*(?P<important>\S+)|' +
    'mtime:(\s)*(?P<mtime>\w+)|' +
    'owner:(\s)*(?P<owner>\S+)|' +
    'paranoid:(\s)*(?P<paranoid>\S+)|' +
    'perms:(\s)*(?P<perms>\w+)|')

class PluginInitError(Exception):
    """Error raised in cases of Plugin initialization errors."""
    pass

class PluginExecutionError(Exception):
    """Error raised in case of Plugin execution errors."""
    pass

class Plugin(object):
    """This is the base class for all Bcfg2 Server plugins.
    Several attributes must be defined in the subclass:
    name : the name of the plugin
    __version__ : a version string
    __author__ : the author/contact for the plugin

    Plugins can provide three basic types of functionality:
      - Structure creation (overloading BuildStructures)
      - Configuration entry binding (overloading HandlesEntry, or loads the Entries table)
      - Data collection (overloading GetProbes/ReceiveData)
    """
    name = 'Plugin'
    __version__ = '$Id$'
    __author__ = 'bcfg-dev@mcs.anl.gov'
    __rmi__ = ['toggle_debug']
    experimental = False
    deprecated = False
    conflicts = []

    def __init__(self, core, datastore):
        object.__init__(self)
        self.Entries = {}
        self.core = core
        self.data = "%s/%s" % (datastore, self.name)
        self.logger = logging.getLogger('Bcfg2.Plugins.%s' % (self.name))
        self.running = True
        self.debug_flag = False

    def toggle_debug(self):
        self.debug_flag = not self.debug_flag

    def debug_log(self, message, flag=None):
        if (flag is None) and self.debug_flag or flag:
            self.logger.error(message)

    @classmethod
    def init_repo(cls, repo):
        path = "%s/%s" % (repo, cls.name)
        os.makedirs(path)

    def shutdown(self):
        self.running = False

class Generator(object):
    """Generator plugins contribute to literal client configurations."""
    def HandlesEntry(self, entry, metadata):
        """This is the slow path method for routing configuration binding requests."""
        return False

    def HandleEntry(self, entry, metadata):
        """This is the slow-path handler for configuration entry binding."""
        raise PluginExecutionError

class Structure(object):
    """Structure Plugins contribute to abstract client configurations."""
    def BuildStructures(self, metadata):
        """Return a list of abstract goal structures for client."""
        raise PluginExecutionError

class Metadata(object):
    """Signal metadata capabilities for this plugin"""
    def add_client(self, client_name, attribs):
        """Add client."""
        pass
    def remove_client(self, client_name):
        """Remove client."""
        pass
    def viz(self, hosts, bundles, key, colors):
        """Create viz str for viz admin mode."""
        pass

    def get_initial_metadata(self, client_name):
        raise PluginExecutionError

    def merge_additional_data(self, imd, source, groups, data):
        raise PluginExecutionError

class Connector(object):
    """Connector Plugins augment client metadata instances."""
    def get_additional_groups(self, metadata):
        """Determine additional groups for metadata."""
        return list()

    def get_additional_data(self, metadata):
        """Determine additional data for metadata instances."""
        return dict()

class Probing(object):
    """Signal probe capability for this plugin."""
    def GetProbes(self, _):
        """Return a set of probes for execution on client."""
        return []

    def ReceiveData(self, _, dummy):
        """Receive probe results pertaining to client."""
        pass

class Statistics(object):
    """Signal statistics handling capability."""
    def process_statistics(self, client, xdata):
        pass

class ThreadedStatistics(Statistics,
                         threading.Thread):
    """Threaded statistics handling capability."""
    def __init__(self, core, datastore):
        Statistics.__init__(self)
        threading.Thread.__init__(self)
        # Event from the core signaling an exit
        self.terminate = core.terminate
        self.work_queue = Queue.Queue(100000)
        self.pending_file = "%s/etc/%s.pending" % (datastore, self.__class__.__name__)
        self.daemon = True
        self.start()

    def save(self):
        """Save any pending data to a file."""
        pending_data = []
        try:
            while not self.work_queue.empty():
                (metadata, data) = self.work_queue.get_nowait()
                try:
                    pending_data.append( ( metadata.hostname, lxml.etree.tostring(data) ) )
                except:
                    self.logger.warning("Dropping interaction for %s" % metadata.hostname)
        except Queue.Empty:
            pass

        try:
            savefile = open(self.pending_file, 'w')
            pickle.dump(pending_data, savefile)
            savefile.close()
            self.logger.info("Saved pending %s data" % self.__class__.__name__)
        except:
            self.logger.warning("Failed to save pending data")

    def load(self):
        """Load any pending data to a file."""
        if not os.path.exists(self.pending_file):
            return True
        pending_data = []
        try:
            savefile = open(self.pending_file, 'r')
            pending_data = pickle.load(savefile)
            savefile.close()
        except Exception, e:
            self.logger.warning("Failed to load pending data: %s" % e)
        for (pmetadata, pdata) in pending_data:
            # check that shutdown wasnt called early
            if self.terminate.isSet():
                return False

            try:
                while True:
                    try:
		        metadata = self.core.build_metadata(pmetadata)
                        break
                    except Bcfg2.Server.Plugins.Metadata.MetadataRuntimeError:
                        pass

                    self.terminate.wait(5)
                    if self.terminate.isSet():
                        return False

                self.work_queue.put_nowait( (metadata, lxml.etree.fromstring(pdata)) )
            except Queue.Full:
                self.logger.warning("Queue.Full: Failed to load queue data")
                break
            except lxml.etree.LxmlError, lxml_error:
                self.logger.error("Unable to load save interaction: %s" % lxml_error)
            except Bcfg2.Server.Plugins.Metadata.MetadataConsistencyError:
                self.logger.error("Unable to load metadata for save interaction: %s" % pmetadata)
        try:
            os.unlink(self.pending_file)
        except:
            self.logger.error("Failed to unlink save file: %s" % self.pending_file)
        self.logger.info("Loaded pending %s data" % self.__class__.__name__)
        return True

    def run(self):
        if not self.load():
            return
        while not self.terminate.isSet():
            try:
                (xdata, client) = self.work_queue.get(block=True, timeout=2)
            except Queue.Empty:
                continue
            except Exception, e:
                self.logger.error("ThreadedStatistics: %s" % e)
                continue
            self.handle_statistic(xdata, client)
        if not self.work_queue.empty():
            self.save()

    def process_statistics(self, metadata, data):
        warned = False
        try:
            self.work_queue.put_nowait((metadata, copy.deepcopy(data)))
            warned = False
        except Queue.Full:
            if not warned:
                self.logger.warning("%s: Queue is full.  Dropping interactions." % self.__class__.__name__)
            warned = True

    def handle_statistics(self, metadata, data):
        """Handle stats here."""
        pass

class PullSource(object):
    def GetExtra(self, client):
        return []

    def GetCurrentEntry(self, client, e_type, e_name):
        raise PluginExecutionError

class PullTarget(object):
    def AcceptChoices(self, entry, metadata):
        raise PluginExecutionError

    def AcceptPullData(self, specific, new_entry, verbose):
        """This is the null per-plugin implementation
        of bcfg2-admin pull."""
        raise PluginExecutionError

class Decision(object):
    """Signal decision handling capability."""
    def GetDecisions(self, metadata, mode):
        return []

class ValidationError(Exception):
    pass

class StructureValidator(object):
    """Validate/modify goal structures."""
    def validate_structures(self, metadata, structures):
        raise ValidationError, "not implemented"

class GoalValidator(object):
    """Validate/modify configuration goals."""
    def validate_goals(self, metadata, goals):
        raise ValidationError, "not implemented"

class Version(object):
    """Interact with various version control systems."""
    def get_revision(self):
        return []
    def commit_data(self):
        pass

# the rest of the file contains classes for coherent file caching

class FileBacked(object):
    """This object caches file data in memory.
    HandleEvent is called whenever fam registers an event.
    Index can parse the data into member data as required.
    This object is meant to be used as a part of DirectoryBacked.
    """

    def __init__(self, name):
        object.__init__(self)
        self.data = ''
        self.name = name

    def HandleEvent(self, event=None):
        """Read file upon update."""
        if event and event.code2str() not in ['exists', 'changed', 'created']:
            return
        try:
            self.data = file(self.name).read()
            self.Index()
        except IOError:
            logger.error("Failed to read file %s" % (self.name))

    def Index(self):
        """Update local data structures based on current file state"""
        pass

class DirectoryBacked(object):
    """This object is a coherent cache for a filesystem hierarchy of files."""
    __child__ = FileBacked
    patterns = re.compile('.*')

    def __init__(self, name, fam):
        object.__init__(self)
        self.name = name
        self.fam = fam
        self.entries = {}
        self.inventory = False
        fam.AddMonitor(name, self)

    def __getitem__(self, key):
        return self.entries[key]

    def __iter__(self):
        return self.entries.iteritems()

    def AddEntry(self, name):
        """Add new entry to data structures upon file creation."""
        if name == '':
            logger.info("got add for empty name")
        elif name in self.entries:
            self.entries[name].HandleEvent()
        else:
            if ((name[-1] == '~') or
                (name[:2] == '.#') or
                (name[-4:] == '.swp') or
                (name in ['SCCS', '.svn'])):
                return
            if not self.patterns.match(name):
                return
            self.entries[name] = self.__child__('%s/%s' % (self.name, name))
            self.entries[name].HandleEvent()

    def HandleEvent(self, event):
        """Propagate fam events to underlying objects."""
        action = event.code2str()
        if event.filename == '':
            logger.info("Got event for blank filename")
            return
        if action == 'exists':
            if event.filename != self.name:
                self.AddEntry(event.filename)
        elif action == 'created':
            self.AddEntry(event.filename)
        elif action == 'changed':
            if event.filename in self.entries:
                self.entries[event.filename].HandleEvent(event)
        elif action == 'deleted':
            if event.filename in self.entries:
                del self.entries[event.filename]
        elif action in ['endExist']:
            pass
        else:
            print "Got unknown event %s %s %s" % (event.requestID,
                                                  event.code2str(),
                                                  event.filename)

class XMLFileBacked(FileBacked):
    """
    This object is a coherent cache for an XML file to be used as a
    part of DirectoryBacked.
    """
    __identifier__ = 'name'

    def __init__(self, filename):
        self.label = "dummy"
        self.entries = []
        FileBacked.__init__(self, filename)

    def Index(self):
        """Build local data structures."""
        try:
            xdata = XML(self.data)
        except XMLSyntaxError:
            logger.error("Failed to parse %s"%(self.name))
            return
        self.label = xdata.attrib[self.__identifier__]
        self.entries = xdata.getchildren()

    def __iter__(self):
        return iter(self.entries)

class SingleXMLFileBacked(XMLFileBacked):
    """This object is a coherent cache for an independent XML file."""
    def __init__(self, filename, fam):
        XMLFileBacked.__init__(self, filename)
        fam.AddMonitor(filename, self)

class StructFile(XMLFileBacked):
    """This file contains a set of structure file formatting logic."""
    def __init__(self, name):
        XMLFileBacked.__init__(self, name)
        self.fragments = {}

    def Index(self):
        """Build internal data structures."""
        try:
            xdata = lxml.etree.XML(self.data)
        except lxml.etree.XMLSyntaxError:
            logger.error("Failed to parse file %s" % self.name)
            return
        self.fragments = {}
        work = {lambda x:True: xdata.getchildren()}
        while work:
            (predicate, worklist) = work.popitem()
            self.fragments[predicate] = [item for item in worklist if item.tag != 'Group'
                                         and not isinstance(item, lxml.etree._Comment)]
            for group in [item for item in worklist if item.tag == 'Group']:
                # if only python had forceable early-binding
                if group.get('negate', 'false') in ['true', 'True']:
                    cmd = "lambda x:'%s' not in x.groups and predicate(x)"
                else:
                    cmd = "lambda x:'%s' in x.groups and predicate(x)"

                newpred = eval(cmd % (group.get('name')), {'predicate':predicate})
                work[newpred] = group.getchildren()

    def Match(self, metadata):
        """Return matching fragments of independent."""
        matching = [frag for (pred, frag) in self.fragments.iteritems() if pred(metadata)]
        if matching:
            return reduce(lambda x, y:x+y, matching)
        logger.error("File %s got null match" % (self.name))
        return []

class INode:
    """
    LNodes provide lists of things available at a particular
    group intersection.
    """
    raw = {'Client':"lambda x:'%s' == x.hostname and predicate(x)",
           'Group':"lambda x:'%s' in x.groups and predicate(x)"}
    nraw = {'Client':"lambda x:'%s' != x.hostname and predicate(x)",
            'Group':"lambda x:'%s' not in x.groups and predicate(x)"}
    containers = ['Group', 'Client']
    ignore = []

    def __init__(self, data, idict, parent=None):
        self.data = data
        self.contents = {}
        if parent == None:
            self.predicate = lambda x:True
        else:
            predicate = parent.predicate
            if data.get('negate', 'false') in ['true', 'True']:
                psrc = self.nraw
            else:
                psrc = self.raw
            if data.tag in psrc.keys():
                self.predicate = eval(psrc[data.tag] % (data.get('name')),
                                      {'predicate':predicate})
            else:
                raise Exception
        mytype = self.__class__
        self.children = []
        for item in data.getchildren():
            if item.tag in self.ignore:
                continue
            elif item.tag in self.containers:
                self.children.append(mytype(item, idict, self))
            else:
                try:
                    self.contents[item.tag][item.get('name')] = item.attrib
                except KeyError:
                    self.contents[item.tag] = {item.get('name'):item.attrib}
                if item.text:
                    self.contents[item.tag]['__text__'] = item.text
                try:
                    idict[item.tag].append(item.get('name'))
                except KeyError:
                    idict[item.tag] = [item.get('name')]

    def Match(self, metadata, data):
        """Return a dictionary of package mappings."""
        if self.predicate(metadata):
            for key in self.contents:
                try:
                    data[key].update(self.contents[key])
                except:
                    data[key] = {}
                    data[key].update(self.contents[key])
            for child in self.children:
                child.Match(metadata, data)

class XMLSrc(XMLFileBacked):
    """XMLSrc files contain a LNode hierarchy that returns matching entries."""
    __node__ = INode
    __cacheobj__ = dict

    def __init__(self, filename, noprio=False):
        XMLFileBacked.__init__(self, filename)
        self.items = {}
        self.cache = None
        self.pnode = None
        self.priority = -1
        self.noprio = noprio

    def HandleEvent(self, _=None):
        """Read file upon update."""
        try:
            data = file(self.name).read()
        except IOError:
            logger.error("Failed to read file %s" % (self.name))
            return
        self.items = {}
        try:
            xdata = lxml.etree.XML(data)
        except lxml.etree.XMLSyntaxError:
            logger.error("Failed to parse file %s" % (self.name))
            return
        self.pnode = self.__node__(xdata, self.items)
        self.cache = None
        try:
            self.priority = int(xdata.get('priority'))
        except (ValueError, TypeError):
            if not self.noprio:
                logger.error("Got bogus priority %s for file %s" % (xdata.get('priority'), self.name))
        del xdata, data

    def Cache(self, metadata):
        """Build a package dict for a given host."""
        if self.cache == None or self.cache[0] != metadata:
            cache = (metadata, self.__cacheobj__())
            if self.pnode == None:
                logger.error("Cache method called early for %s; forcing data load" % (self.name))
                self.HandleEvent()
                return
            self.pnode.Match(metadata, cache[1])
            self.cache = cache

class XMLDirectoryBacked(DirectoryBacked):
    """Directorybacked for *.xml."""
    patterns = re.compile('.*\.xml')

class PrioDir(Plugin, Generator, XMLDirectoryBacked):
    """This is a generator that handles package assignments."""
    name = 'PrioDir'
    __child__ = XMLSrc

    def __init__(self, core, datastore):
        Plugin.__init__(self, core, datastore)
        Generator.__init__(self)
        try:
            XMLDirectoryBacked.__init__(self, self.data, self.core.fam)
        except OSError:
            self.logger.error("Failed to load %s indices" % (self.name))
            raise PluginInitError

    def HandleEvent(self, event):
        """Handle events and update dispatch table."""
        XMLDirectoryBacked.HandleEvent(self, event)
        self.Entries = {}
        for src in self.entries.values():
            for itype, children in src.items.iteritems():
                for child in children:
                    try:
                        self.Entries[itype][child] = self.BindEntry
                    except KeyError:
                        self.Entries[itype] = {child: self.BindEntry}

    def BindEntry(self, entry, metadata):
        """Check package lists of package entries."""
        [src.Cache(metadata) for src in self.entries.values()]
        name = entry.get('name')
        if not src.cache:
            self.logger.error("Called before data loaded")
            raise PluginExecutionError
        matching = [src for src in self.entries.values()
                    if src.cache and entry.tag in src.cache[1]
                    and src.cache[1][entry.tag].has_key(name)]
        if len(matching) == 0:
            raise PluginExecutionError
        elif len(matching) == 1:
            index = 0
        else:
            prio = [int(src.priority) for src in matching]
            if prio.count(max(prio)) > 1:
                self.logger.error("Found conflicting sources with "
                                  "same priority for %s, %s %s" %
                                  (metadata.hostname,
                                   entry.tag.lower(), entry.get('name')))
                self.logger.error([item.name for item in matching])
                self.logger.error("Priority was %s" % max(prio))
                raise PluginExecutionError
            index = prio.index(max(prio))

        data = matching[index].cache[1][entry.tag][name]
        if '__text__' in data:
            entry.text = data['__text__']
        if '__children__' in data:
            [entry.append(copy.deepcopy(item)) for item in data['__children__']]
        [entry.attrib.__setitem__(key, data[key]) for key in data.keys() \
         if not key.startswith('__')]

# new unified EntrySet backend

class SpecificityError(Exception):
    """Thrown in case of filename parse failure."""
    pass

class Specificity:

    def __init__(self, all=False, group=False, hostname=False, prio=0, delta=False):
        self.hostname = hostname
        self.all = all
        self.group = group
        self.prio = prio
        self.delta = delta

    def matches(self, metadata):
        return self.all or \
               self.hostname == metadata.hostname or \
               self.group in metadata.groups

    def __cmp__(self, other):
        """Sort most to least specific."""
        if self.all:
            return 1
        if self.group:
            if other.hostname:
                return 1
            if other.group and other.prio > self.prio:
                return 1
            if other.group and other.prio == self.prio:
                return 0
        return -1

    def more_specific(self, other):
        """Test if self is more specific than other."""
        if self.all:
            True
        elif self.group:
            if other.hostname:
                return True
            elif other.group and other.prio > self.prio:
                return True
        return False

class SpecificData(object):
    def __init__(self, name, specific, encoding):
        self.name = name
        self.specific = specific

    def handle_event(self, event):
        if event.code2str() == 'deleted':
            return
        try:
            self.data = open(self.name).read()
        except:
            logger.error("Failed to read file %s" % self.name)

class EntrySet:
    """Entry sets deal with the host- and group-specific entries."""
    ignore = re.compile("^(\.#.*|.*~|\\..*\\.(sw[px]))$")
    def __init__(self, basename, path, entry_type, encoding):
        self.path = path
        self.entry_type = entry_type
        self.entries = {}
        self.metadata = default_file_metadata.copy()
        self.infoxml = None
        self.encoding = encoding
        pattern = '(.*/)?%s(\.((H_(?P<hostname>\S+))|' % basename
        pattern += '(G(?P<prio>\d+)_(?P<group>\S+))))?$'
        self.specific = re.compile(pattern)

    def get_matching(self, metadata):
        return [item for item in self.entries.values() \
                if item.specific.matches(metadata)]

    def handle_event(self, event):
        """Handle FAM events for the TemplateSet."""
        action = event.code2str()

        if event.filename in ['info', 'info.xml', ':info']:
            if action in ['exists', 'created', 'changed']:
                self.update_metadata(event)
            elif action == 'deleted':
                self.reset_metadata(event)
            return

        if action in ['exists', 'created']:
            self.entry_init(event)
        else:
            if event.filename not in self.entries:
                return
            if action == 'changed':
                self.entries[event.filename].handle_event(event)
            elif action == 'deleted':
                del self.entries[event.filename]

    def entry_init(self, event):
        """Handle template and info file creation."""
        if event.filename in self.entries:
            logger.warn("Got duplicate add for %s" % event.filename)
        else:
            fpath = "%s/%s" % (self.path, event.filename)
            try:
                spec = self.specificity_from_filename(event.filename)
            except SpecificityError:
                if not self.ignore.match(event.filename):
                    logger.error("Could not process filename %s; ignoring" % fpath)
                return
            self.entries[event.filename] = self.entry_type(fpath,
                                                           spec, self.encoding)
        self.entries[event.filename].handle_event(event)

    def specificity_from_filename(self, fname):
        """Construct a specificity instance from a filename and regex."""
        data = self.specific.match(fname)
        if not data:
            raise SpecificityError(fname)
        kwargs = {}
        if data.group('hostname'):
            kwargs['hostname'] = data.group('hostname')
        elif data.group('group'):
            kwargs['group'] = data.group('group')
            kwargs['prio'] = int(data.group('prio'))
        else:
            kwargs['all'] = True
        if 'delta' in data.groupdict():
            kwargs['delta'] = data.group('delta')
        return Specificity(**kwargs)

    def update_metadata(self, event):
        """Process info and info.xml files for the templates."""
        fpath = "%s/%s" % (self.path, event.filename)
        if event.filename == 'info.xml':
            if not self.infoxml:
                self.infoxml = XMLSrc(fpath, True)
            self.infoxml.HandleEvent(event)
        elif event.filename in [':info', 'info']:
            for line in open(fpath).readlines():
                match = info_regex.match(line)
                if not match:
                    logger.warning("Failed to match line: %s"%line)
                    continue
                else:
                    mgd = match.groupdict()
                    for key, value in mgd.iteritems():
                        if value:
                            self.metadata[key] = value
                    if len(self.metadata['perms']) == 3:
                        self.metadata['perms'] = "0%s" % \
                                                 (self.metadata['perms'])

    def reset_metadata(self, event):
        """Reset metadata to defaults if info or info.xml removed."""
        if event.filename == 'info.xml':
            self.infoxml = None
        elif event.filename == 'info':
            self.metadata = default_file_metadata.copy()

    def group_sortfunc(self, x, y):
        """sort groups by their priority"""
        return cmp(x.specific.prio, y.specific.prio)

    def bind_info_to_entry(self, entry, metadata):
        if not self.infoxml:
            for key in self.metadata:
                entry.set(key, self.metadata[key])
        else:
            mdata = {}
            self.infoxml.pnode.Match(metadata, mdata)
            if 'Info' not in mdata:
                logger.error("Failed to set metadata for file %s" % \
                             (entry.get('name')))
                raise PluginExecutionError
            [entry.attrib.__setitem__(key, value) \
             for (key, value) in mdata['Info'][None].iteritems()]

    def bind_entry(self, entry, metadata):
        """Return the appropriate interpreted template from the set of available templates."""
        self.bind_info_to_entry(entry, metadata)
        matching = self.get_matching(metadata)

        hspec = [ent for ent in matching if ent.specific.hostname]
        if hspec:
            return hspec[0].bind_entry(entry, metadata)

        gspec = [ent for ent in matching if ent.specific.group]
        if gspec:
            gspec.sort(self.group_sortfunc)
            return gspec[-1].bind_entry(entry, metadata)

        aspec = [ent for ent in matching if ent.specific.all]
        if aspec:
            return aspec[0].bind_entry(entry, metadata)

        raise PluginExecutionError

class GroupSpool(Plugin, Generator):
    """Unified interface for handling group-specific data (e.g. .G## files)."""
    name = 'GroupSpool'
    __version__ = '$Id$'
    __author__ = 'bcfg-dev@mcs.anl.gov'
    filename_pattern = ""
    es_child_cls = object
    es_cls = EntrySet

    def __init__(self, core, datastore):
        Plugin.__init__(self, core, datastore)
        Generator.__init__(self)
        if self.data[-1] == '/':
            self.data = self.data[:-1]
        self.Entries['Path'] = {}
        self.entries = {}
        self.handles = {}
        self.AddDirectoryMonitor('')
        self.encoding = core.encoding

    def HandleEvent(self, event):
        """Unified FAM event handler for DirShadow."""
        action = event.code2str()
        if event.filename[0] == '/':
            return
        epath = "".join([self.data, self.handles[event.requestID],
                         event.filename])
        if posixpath.isdir(epath):
            ident = self.handles[event.requestID] + event.filename
        else:
            ident = self.handles[event.requestID][:-1]

        if action in ['exists', 'created']:
            if posixpath.isdir(epath):
                self.AddDirectoryMonitor(epath[len(self.data):])
            if ident not in self.entries and posixpath.isfile(epath):
                dirpath = "".join([self.data, ident])
                self.entries[ident] = self.es_cls(self.filename_pattern,
                                                  dirpath,
                                                  self.es_child_cls,
                                                  self.encoding)
                self.Entries['Path'][ident] = self.entries[ident].bind_entry
            if not posixpath.isdir(epath):
                # do not pass through directory events
                self.entries[ident].handle_event(event)
        if action == 'changed':
            self.entries[ident].handle_event(event)
        elif action == 'deleted':
            fbase = self.handles[event.requestID] + event.filename
            if fbase in self.entries:
                # a directory was deleted
                del self.entries[fbase]
                del self.Entries['Path'][fbase]
            else:
                self.entries[ident].handle_event(event)

    def AddDirectoryMonitor(self, relative):
        """Add new directory to FAM structures."""
        if not relative.endswith('/'):
            relative += '/'
        name = self.data + relative
        if relative not in self.handles.values():
            if not posixpath.isdir(name):
                print "Failed to open directory %s" % (name)
                return
            reqid = self.core.fam.AddMonitor(name, self)
            self.handles[reqid] = relative
