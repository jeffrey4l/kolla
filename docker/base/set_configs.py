#!/usr/bin/env python

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

import argparse
import glob
import grp
import json
import logging
import os
import pwd
import shutil
import sys


# TODO(rhallisey): add docstring.
logging.basicConfig()
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class ConfigException(Exception):
    message = 'Config exception'

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __str__(self):
        return self.message % self.kwargs


class ConfigFileError(ConfigException):
    pass


class BadConfigStrategy(ConfigException):
    message = 'KOLLA_CONFIG_STRATEGY is not set properly'


class SourceFileNotFound(ConfigException):
    message = '%(source)s file do not found'


class ConfigFileBadState(ConfigException):
    message = '%(config_file)s has bad state'


class ConfigFile(object):

    def __init__(self, source, dest, owner, perm, optional=False):
        self.source = source
        self.dest = dest
        self.owner = owner
        self.perm = perm
        self.optional = optional

    def _copy_dir(self, source, dest):
        shutil.copytree(source, dest)
        for root, dirs, files in os.walk(dest):
            for dir_ in dirs:
                self._set_permission(os.path.join(root, dir_))
            for file_ in files:
                self._set_permission(os.path.join(root, file_))

    def _copy_file(self, source, dest):
        # dest endswith / means copy the <source> to <dest> folder
        if dest.endswith(os.sep):
            dest = os.path.join(dest, os.path.basename(source))
        LOG.info('Coping file from %s to %s', source, dest)
        shutil.copy(source, dest)
        self._set_permission(dest)

    def _set_permission(self, path):
        user = pwd.getpwnam(self.owner)
        uid, gid = user.pw_uid, user.pw_gid
        os.chown(path, uid, gid)

        perm = int((self.perm), 0)
        os.chmod(path, perm)

    def copy(self):
        if os.path.exists(self.dest):
            LOG.info("Removing existing destination: %s", self.dest)
            if os.path.isdir(self.dest):
                shutil.rmtree(self.dest)
            else:
                os.remove(self.dest)
        elif not os.path.exists(os.path.dirname(self.dest)):
            # create dest parent dir
            os.makedirs(os.path.dirname(self.dest))

        sources = glob.glob(self.source)

        if not self.optional:
            if not sources:
                raise SourceFileNotFound(source=self.source)
            # when the length of sources is 1, we may use absolute path. test
            # whether it exist
            if len(sources) == 1 and not os.path.exists(sources[0]):
                raise SourceFileNotFound(source=self.source)

        else:
            # skip when source is optional and not exist
            if not sources or (len(sources) == 1 and
                               not os.path.exists(sources[0])):
                return

        for source in sources:
            if self.optional and not os.path.exists(source):
                continue
            if os.path.isdir(source):
                self._copy_dir(source, self.dest)
            else:
                self._copy_file(source, self.dest)

    def _cmp_file(self, source, dest):
        # check exsit
        if (os.path.exists(source) and
                not self.optional and
                not os.path.exists(dest)):
            return False
        # check content
        with open(source) as f1, open(dest) as f2:
            if f1.read() != f2.read():
                LOG.error('The content of source file(%s) and'
                          ' dest file(%s) are not equal.', source, dest)
                return False
        # check perm
        file_stat = os.stat(dest)
        actual_perm = oct(file_stat.st_mode)[-4:]
        if self.perm != actual_perm:
            LOG.error('Dest file does not have expected perm: %s, actual: %s',
                      self.perm, actual_perm)
            return False
        # check owner
        actual_user = pwd.getpwuid(file_stat.st_uid)
        if actual_user.pw_name != self.owner:
            LOG.error('Dest file does not have expected user: %s,'
                      ' actual: %s ', self.owner, actual_user.pw_name)
            return False
        actual_group = grp.getgrgid(file_stat.st_gid)
        if actual_group.gr_name != self.owner:
            LOG.error('Dest file does not have expected group: %s,'
                      ' actual: %s ', self.owner, actual_group.gr_name)
            return False
        return True

    def _cmp_dir(self, source, dest):
        for root, dirs, files in os.walk(source):
            for dir_ in dirs:
                full_path = os.path.join(root, dir_)
                dest_full_path = os.path.join(dest, os.path.relpath(source,
                                                                    full_path))
                dir_stat = os.stat(dest_full_path)
                actual_perm = oct(dir_stat.st_mode)[-4:]
                if self.perm != actual_perm:
                    LOG.error('Dest dir does not have expected perm: %s,'
                              ' acutal %s', self.perm, actual_perm)
                    return False
            for file_ in files:
                full_path = os.path.join(root, file_)
                dest_full_path = os.path.join(dest, os.path.relpath(source,
                                                                    full_path))
                if not self._cmp_file(full_path, dest_full_path):
                    return False
        return True

    def check(self):
        bad_state_files = []
        sources = glob.glob(self.source)
        if not sources and not self.optional:
            raise SourceFileNotFound(source=self.source)
        for source in sources:
            if os.path.isdir(source) and not self._cmp_dir(source, self.dest):
                bad_state_files.append(source)
            elif not self._cmp_file(source, self.dest):
                bad_state_files.append(source)
        if len(bad_state_files) != 0:
            LOG.error('Following files are in bad state: %s', bad_state_files)
            raise ConfigFileBadState(config_file=self.source)


def validate_config(config):
    required_keys = {'source', 'dest', 'owner', 'perm'}

    if 'command' not in config:
        LOG.error('Config is missing required "command" key')
        raise ConfigFileError()

    # Validate config sections
    for data in config.get('config_files', list()):
        # Verify required keys exist.
        if not data.viewkeys() >= required_keys:
            LOG.error("Config is missing required keys: %s", required_keys)
            raise ConfigFileError()


def load_config():
    def load_from_env():
        config_raw = os.environ.get("KOLLA_CONFIG")
        if config_raw is None:
            return None

        # Attempt to read config
        try:
            return json.loads(config_raw)
        except ValueError:
            LOG.error('Invalid json for Kolla config')
            raise

    def load_from_file():
        config_file = '/var/lib/kolla/config_files/config.json'
        LOG.info("Loading config file at %s", config_file)

        # Attempt to read config file
        with open(config_file) as f:
            try:
                return json.load(f)
            except ValueError:
                LOG.error("Invalid json file found at %s", config_file)
                raise
            except IOError as e:
                LOG.error("Could not read file %s: %r", config_file, e)
                raise

    config = load_from_env()
    if config is None:
        config = load_from_file()

    LOG.info('Validating config file')
    validate_config(config)
    return config


def copy_config(config):
    if 'config_files' in config:
        LOG.info('Copying service configuration files')
        for data in config['config_files']:
            config_file = ConfigFile(**data)
            config_file.copy()
    else:
        LOG.debug('No files to copy found in config')

    LOG.info('Writing out command to execute')
    LOG.debug("Command is: %s", config['command'])
    # The value from the 'command' key will be written to '/run_command'
    with open('/run_command', 'w+') as f:
        f.write(config['command'])


def execute_config_strategy(config):
    config_strategy = os.environ.get("KOLLA_CONFIG_STRATEGY")
    LOG.info("Kolla config strategy set to: %s", config_strategy)
    if config_strategy == "COPY_ALWAYS":
        copy_config(config)
    elif config_strategy == "COPY_ONCE":
        if os.path.exists('/configured'):
            LOG.info("The config strategy prevents copying new configs")
        else:
            copy_config(config)
            os.mknod('/configured')
    else:
        raise BadConfigStrategy()


def execute_config_check(config):
    for data in config['config_files']:
        config_file = ConfigFile(**data)
        config_file.check()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check',
                        action='store_true',
                        required=False,
                        help='Check whether the configs changed')
    args = parser.parse_args()

    config = load_config()

    if args.check:
        execute_config_check(config)
    else:
        execute_config_strategy(config)


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except ConfigException:
        LOG.exception('Config error:')
        exit_code = 1
    except Exception:
        LOG.exception('Unexpected error:')
        exit_code = 1
    sys.exit(exit_code)
