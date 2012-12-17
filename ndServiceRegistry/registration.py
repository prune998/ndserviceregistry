#!/usr/bin/python
#
# Copyright 2012 Nextdoor.com, Inc.
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

"""Kazoo Zookeeper znode registration client

This object type handles the initial registration, updating of registered
data, and connection state changes from the supplied ServiceRegistry object.

The idea here is that the Registration object creates a Watcher object to
keep an eye on the 'node' that we want to register. This Watcher object
will then trigger the this Registration object to create/update or delete
the node, based on the desired state (self.state() and self.set_state()).

Args:
    zk: kazoo.client.KazooClient object reference
    path: (string) The full path to register (including hostname,
          if applicable)
    data: (dict/string) Data to apply to the supplied path
    state: (Boolean) whether to create, or delete the path from ZooKeeper

Example:
    Register a new node:
    >>> r = EphemeralNode(zk, '/services/ssh/foo:123', 'my data', True)
    >>> r.data()
    {u'pid': 8364, u'string_value': u'my data', u'created': u'2012-12-14 21:17:50'}

    Now change the nodes data
    >>> r.set_data('some other data')
    >>> r.data()
    {u'pid': 8364, u'string_value': u'some other data', u'created': u'2012-12-14 21:18:26'}

    De-register the node
    >>> r.set_state(False)
    >>> r.data()
    >>> r.get()
    {'stat': None, 'data': None, 'children': {}}

Copyright 2012 Nextdoor Inc."""

__author__ = 'matt@nextdoor.com (Matt Wise)'

import logging
import time
import sys

from ndServiceRegistry import funcs
from ndServiceRegistry.watcher import Watcher

# For KazooServiceRegistry Class
import kazoo.exceptions

# Our default variables
from version import __version__ as VERSION

TIMEOUT = 30


class Registration(object):
    """An object that registers a znode with ZooKeeper."""

    LOGGING = 'ndServiceRegistry.Registration'

    def __init__(self, zk, path, data=None, state=True):
        # Create our logger
        self.log = logging.getLogger('%s.%s' % (self.LOGGING, path))

        # Set our local variables
        self._zk = zk
        self._path = path
        self._state = state

        # Store both encdoed-string and decoded-dict versions of our 'data'
        # for comparison purposes later.
        self._data = data
        self._encoded_data = funcs.encode(data)
        self._decoded_data = funcs.decode(self._encoded_data)

        # Make sure that we have a watcher on the path we care about
        self._watcher = Watcher(self._zk,
                                path=self._path,
                                watch_children=False,
                                callback=self._update)

    def data(self):
        """Returns live node data from Watcher object."""
        return self._watcher.data()

    def get(self):
        """Returns live node information from Watcher object."""
        return self._watcher.get()

    def set_data(self, data):
        """Sets self._data.

        Args:
            data: String or Dict of data to register with this object."""

        if not data == self._data:
            self._data = data
            self._encoded_data = funcs.encode(data)
            self._decoded_data = funcs.decode(self._encoded_data)
            self._set_data()

    def _set_data(self):
        try:
            self._zk.retry(self._zk.set, self._path, value=self._encoded_data)
            self.log.debug('Updated with data: %s' % self._encoded_data)
        except kazoo.exceptions.NoAuthError, e:
            self.log.error('No authorization to set node.')
            pass
        except Exception, e:
            self.log.error('Received exception. Moving on, will re-attempt ' \
                           'when Watcher notifies us of a state change: %s '
                           % e)
            pass

    def stop(self):
        """Disables our registration of the node."""
        self.set_state(False)
        
    def start(self):
        """Enables our registration of the node."""
        self.set_state(True)

    def state(self):
        """Returns self._state"""
        return self._state

    def set_state(self, state):
        """Sets the state of our registration.

        Updates the internal 'wanted' state of this object. If True, we want
        to be actively registered with Zookeeper. If False, we want to make
        sure we're not registered with Zookeeper.

        Args:
            state: True or False"""

        if self._state == state:
            return

        self._state = state
        self._set_state(self._state)

    def _set_state(self, state):
        if state == True:
            # Register our connection with zookeeper
            try:
                self.log.debug('Registering...')
                self._zk.retry(self._zk.create, self._path,
                               value=self._encoded_data,
                               ephemeral=self._ephemeral, makepath=True)
                self.log.info('Registered with data: %s' % self._encoded_data)
                pass
            except kazoo.exceptions.NodeExistsError, e:
                # Node exists ... possible this callback got claled multiple
                # times
                pass
            except kazoo.exceptions.NoAuthError, e:
                self.log.error('No authorization to create node.')
                pass
            except Exception, e:
                self.log.error('Received exception. Moving on, will ' \
                               're-attempt when Watcher notifies us of a ' \
                               'state change: %s ' % e)
                pass
            pass
        elif state == False:
            # Try to delete the node
            self.log.debug('Attempting de-registration...')
            try:
                self._zk.retry(self._zk.delete, self._path)
            except kazoo.exceptions.NoAuthError, e:
                # The node exists, but we don't even have authorization to read
                # it. We certainly will not have access then to change it below,
                # so return false. We'll retry again very soon.
                self.log.error('No authorization to delete node.')
                pass
            except Exception, e:
                self.log.error('Received exception. Moving on, will ' \
                               're-attempt when Watcher notifies us of a ' \
                               'state change: %s ' % e)
                pass
            return

    def update(self, data=None, state=None):
        """Triggers near-immediate run of the self._update() function.

        If data or state are supplied, these are updated before triggering the
        update.

        Args:
            data: (String/Dict) data to register with this object.
            state: (Boolean) whether to register or unregister this object
        """

        if data:
            self.set_data(data)

        if state:
            self.set_state(state)

    def _update(self, data):
        """Registers a supplied node (full path and nodename).

        Raises:
            NoAuthException: If no authorization to update node"""

        # Try to delete the node
        self.log.debug('Called with data: %s' % data)
        self.log.debug('Wanted state: %s' % self.state())

        if self.state() is False and data['stat'] != None:
            # THe node exists because data['stat'] has data, but our
            # desired state is False. De-register the node.
            self._set_state(False)
        elif self.state() is True and data['stat'] == None:
            # The node does NOT exist because data['stat'] is None,
            # but our desired state is True. Register the node.
            self._set_state(True)
            return
        elif self.state() is True and not data['data'] == self._decoded_data:
            # Lastly, the node is registered, and we want it to be. However,
            # the data with the node is incorrect. Change it.
            self.log.warning('Registered node had different data.')
            self._set_data()


class EphemeralNode(Registration):
    """This is a node-specific ephemeral object that we register and monitor.

    The node registered with Zookeeper is ephemeral, so if we lose our
    connection to the service, we have to re-register the data."""

    LOGGING = 'ndServiceRegistry.Registration.EphemeralNode'

    def __init__(self, zk, path, data, state=True):
        """Sets the ZooKeeper registration up to be ephemeral.

        Sets ephemeral=True when we register the Zookeeper node, and
        initiates a simple thread that monitors whether or not our node
        registration has been lost. If it has, it re-registers it."""

        self._ephemeral = True
        Registration.__init__(self, zk, path, data, state=state)

    def stop(self):
        """De-registers from Zookeeper, then calls SuperClass stop() method."""
        # Set our state to disabled to force the de-registration of our node
        self.set_state(False)

        # Call our super class stop()
        return super(EphemeralNode, self).stop()
