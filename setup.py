#!/usr/bin/env python

from distutils.core import setup
try:
    from sphinx.setup_command import BuildDoc
    cmdclass = {'build_sphinx': BuildDoc}
except ImportError:
    cmdclass = {}
from glob import glob

setup(cmdclass=cmdclass,
      name="Bcfg2",
      version="1.1.0",
      description="Bcfg2 Server",
      author="Narayan Desai",
      author_email="desai@mcs.anl.gov",
      packages=["Bcfg2",
                "Bcfg2.Client",
                "Bcfg2.Client.Tools",
                'Bcfg2.Server',
                "Bcfg2.Server.Admin",
                "Bcfg2.Server.Hostbase",
                "Bcfg2.Server.Hostbase.hostbase",
                "Bcfg2.Server.Plugins",
                "Bcfg2.Server.Reports",
                "Bcfg2.Server.Reports.reports",
                "Bcfg2.Server.Reports.reports.templatetags",
                "Bcfg2.Server.Snapshots",
                ],
      package_dir = {'Bcfg2':'src/lib'},
      package_data = {'Bcfg2.Server.Reports.reports':['fixtures/*.xml',
                'templates/*.html', 'templates/*/*.html',
                'templates/*/*.inc' ] },
      scripts = glob('src/sbin/*'),
      data_files = [('share/bcfg2/schemas',
                     glob('schemas/*.xsd')),
                    ('share/bcfg2/xsl-transforms',
                     glob('reports/xsl-transforms/*.xsl')),
                    ('share/bcfg2/xsl-transforms/xsl-transform-includes',
                     glob('reports/xsl-transforms/xsl-transform-includes/*.xsl')),
                    ('share/bcfg2', ['reports/reports.wsgi']),
                    ('share/man/man1', glob("man/bcfg2.1")),
                    ('share/man/man5', glob("man/*.5")),
                    ('share/man/man8', glob("man/*.8")),
                    ('share/bcfg2/Hostbase/templates',
                     glob('src/lib/Server/Hostbase/hostbase/webtemplates/*.*')),
                    ('share/bcfg2/Hostbase/templates/hostbase',
                     glob('src/lib/Server/Hostbase/hostbase/webtemplates/hostbase/*')),
                    ('share/bcfg2/Hostbase/repo',
                     glob('src/lib/Server/Hostbase/templates/*')),
                    ('share/bcfg2/site_media',
                     glob('reports/site_media/*')),
                    ]
      )
