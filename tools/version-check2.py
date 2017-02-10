#!/usr/bin/env python2

RELEASE_REPO="https://github.com/openstack/releases"
TARGET="/tmp/releases"

TARBALLS_SITE = "https://tarballs.openstack.org/{project}/{project}-{tag}.tar.gz"
OPENSTACK_RELEASE='ocata'

# clone the repo
import subprocess
import os
import yaml
from oslo_config import cfg
from kolla.common import config

if not os.path.exists(TARGET):
    subprocess.call(['git', 'clone', RELEASE_REPO, TARGET])
else:
    # git pull
    pass

def load_all_info(openstack_release=OPENSTACK_RELEASE):
    projects = {}
    def inner(openstack_release):
        for deliverable in os.listdir(os.path.join(TARGET,'deliverables', openstack_release)):
            with open(os.path.join(TARGET, 'deliverables', openstack_release, deliverable)) as f:
                info = yaml.safe_load(f)
                if 'releases' in info and len(info['releases']) > 0:
                    latest_release = info['releases'][-1]
                    for project in latest_release['projects']:
                        project_name = project['repo'].split('/')[-1]
                        projects[project_name] = latest_release['version']
    inner(openstack_release)
    inner('_independent')
    return projects


def get_project_info(project, openstack_release=OPENSTACK_RELEASE):
    filepath = os.path.join(TARGET, 'deliverables', openstack_release, project+'.yaml')
    with open(filepath) as f:
        project_info = yaml.safe_load(f)
    return project_info

def get_latest_tag(project, openstack_release=OPENSTACK_RELEASE):
    project_info = get_project_info(project, openstack_release)
    return project_info['releases'][-1]['version']

def format_tarballs_url(project, tag):
    return TARBALLS_SITE.format({"project": project,
                                 "tag": tag})

def main():
    conf = cfg.ConfigOpts()
    config.parse(conf, [])
    projects = load_all_info()

    for key, value in config.SOURCES.items():
        # get project name from location
        location = value['location']
        filename = os.path.basename(location)
        project_name = filename.rsplit('-', 1)[0]

        latest_tag = projects.get(project_name, 'None')
        print('%s -> %s -> %s' % (key, project_name, latest_tag))
if __name__ == '__main__':
    main()
