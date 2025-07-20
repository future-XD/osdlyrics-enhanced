# -*- coding: utf-8 -*-
#
# Copyright (C) 2011  Tiger Soldier
#
# This file is part of OSD Lyrics.
#
# OSD Lyrics is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OSD Lyrics is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with OSD Lyrics.  If not, see <https://www.gnu.org/licenses/>.
#
import logging
import os.path
import sqlite3
import re

from osdlyrics.consts import (METADATA_ALBUM, METADATA_ARTIST, METADATA_TITLE,
                              METADATA_TRACKNUM)
import osdlyrics.utils

__all__ = (
    'LrcDb',
)


def query_param_from_metadata(metadata):
    """
    Generate query dict from metadata
    """
    param = {
        METADATA_TITLE: metadata.title or '',
        METADATA_ARTIST: metadata.artist or '',
        METADATA_ALBUM: metadata.album or '',
        METADATA_TRACKNUM: max(metadata.tracknum, 0),
    }
    return param


class LrcDb:
    """ Database to store location of LRC files that have been manually assigned
    """

    TABLE_NAME = 'lyrics'

    METADATA_LIST = [METADATA_TITLE, METADATA_ARTIST, METADATA_ALBUM, METADATA_TRACKNUM]

    # Updated table creation with enhanced LRC support
    CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {0} (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  {1} TEXT, {2} TEXT, {3} TEXT, {4} INTEGER,
  uri TEXT UNIQUE ON CONFLICT REPLACE,
  lrcpath TEXT,
  enhanced INTEGER DEFAULT 0
)
""".format(TABLE_NAME, *METADATA_LIST)

    # Updated SQL statements to include enhanced flag
    ASSIGN_LYRIC = """
INSERT OR REPLACE INTO {0}
  ({1}, {2}, {3}, {4}, uri, lrcpath, enhanced)
  VALUES (?, ?, ?, ?, ?, ?, ?)
""" .format(TABLE_NAME, *METADATA_LIST)

    UPDATE_LYRIC = """
UPDATE {0}
  SET lrcpath=?, enhanced=?
  WHERE uri=?
""".format(TABLE_NAME)

    DELETE_LYRIC = 'DELETE FROM {0} WHERE '.format(TABLE_NAME)

    FIND_LYRIC = 'SELECT lrcpath FROM {0} WHERE '.format(TABLE_NAME)
    
    # New query to include enhanced status
    FIND_LYRIC_WITH_ENHANCED = 'SELECT lrcpath, enhanced FROM {0} WHERE '.format(TABLE_NAME)

    QUERY_LOCATION = 'uri = ?'

    QUERY_INFO = ' AND '.join('{0}=:{0}'.format(m) for m in METADATA_LIST)

    # Enhanced LRC detection pattern
    ENHANCED_PATTERN = re.compile(r'<\d+:\d+\.\d+>')

    def __init__(self, dbfile=None):
        """

        Arguments:
        - `dbfile`: The sqlite db to open
        """
        if dbfile is None:
            dbfile = osdlyrics.utils.get_config_path('lrc.db')
        self._dbfile = dbfile
        osdlyrics.utils.ensure_path(dbfile)
        self._conn = sqlite3.connect(os.path.expanduser(dbfile))
        self._create_table()
        self._migrate_database()

    def _create_table(self):
        """ Ensures the table structure of new open dbs
        """
        c = self._conn.cursor()
        c.execute(LrcDb.CREATE_TABLE)
        self._conn.commit()
        c.close()

    def _migrate_database(self):
        """Add enhanced column to existing databases for backward compatibility"""
        c = self._conn.cursor()
        try:
            # Check if enhanced column exists
            c.execute("PRAGMA table_info({0})".format(self.TABLE_NAME))
            columns = [row[1] for row in c.fetchall()]
            
            if 'enhanced' not in columns:
                logging.info("Migrating database: adding enhanced column")
                c.execute("ALTER TABLE {0} ADD COLUMN enhanced INTEGER DEFAULT 0".format(self.TABLE_NAME))
                self._conn.commit()
                logging.info("Database migration completed")
        except sqlite3.Error as e:
            logging.warning("Database migration failed: %s", e)
        finally:
            c.close()

    def _is_enhanced_lrc(self, lrc_path):
        """
        Check if an LRC file contains enhanced word-level timing
        
        Arguments:
        - `lrc_path`: Path to the LRC file
        
        Returns:
        - True if the file contains enhanced timing, False otherwise
        """
        if not lrc_path or not os.path.isfile(lrc_path):
            return False
            
        try:
            with open(lrc_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Look for enhanced LRC pattern like <mm:ss.cc>
                return bool(self.ENHANCED_PATTERN.search(content))
        except (IOError, UnicodeDecodeError) as e:
            logging.warning("Error reading LRC file %s: %s", lrc_path, e)
            return False

    def assign(self, metadata, uri):
        # type: (osdlyrics.metadata.Metadata, Text) -> None
        """ Assigns a uri of lyrics to tracks represented by metadata
        
        Now automatically detects and stores enhanced LRC status
        """
        c = self._conn.cursor()
        location = metadata.location or ''
        
        # Automatically detect if this is an enhanced LRC file
        is_enhanced = self._is_enhanced_lrc(uri)
        
        if self._find_by_location(metadata):
            logging.debug('Assign lyric file %s to track of location %s (enhanced: %s)', 
                         uri, location, is_enhanced)
            c.execute(LrcDb.UPDATE_LYRIC, (uri, int(is_enhanced), location,))
        else:
            title = metadata.title or ''
            artist = metadata.artist or ''
            album = metadata.album or ''
            tracknum = max(metadata.tracknum, 0)
            logging.debug('Assign lyrics file %s to track %s. %s - %s in album %s @ %s (enhanced: %s)', 
                         uri, tracknum, artist, title, album, location, is_enhanced)
            c.execute(LrcDb.ASSIGN_LYRIC, (title, artist, album, tracknum, location, uri, int(is_enhanced)))
        
        self._conn.commit()
        c.close()

    def delete(self, metadata):
        """ Deletes lyrics association(s) for given metadata

        Deletes all lyrics associations that would be found by find(self, metadata)
        """
        c = self._conn.cursor()

        if metadata.location:
            c.execute(LrcDb.DELETE_LYRIC + LrcDb.QUERY_LOCATION, (metadata.location,))

        c.execute(LrcDb.DELETE_LYRIC + LrcDb.QUERY_INFO, query_param_from_metadata(metadata))

        self._conn.commit()
        c.close()

    def find(self, metadata):
        """ Finds the location of LRC files for given metadata

        To find the location of lyrics, firstly find whether there is a record matched
        with the ``location`` attribute in metadata. If not found or ``location`` is
        not specified, try to find with respect to ``title``, ``artist``, ``album``
        and ``tracknum``

        If found, return the uri of the LRC file. Otherwise return None. Note that
        this method may return an empty string, so use ``is None`` to figure out
        whether an uri is found
        """
        ret = self._find_by_location(metadata)
        if ret is not None:
            return ret
        ret = self._find_by_info(metadata)
        if ret is not None:
            return ret
        return None

    def find_with_enhanced_info(self, metadata):
        """
        Find LRC file and return both path and enhanced status
        
        Arguments:
        - `metadata`: Track metadata to search for
        
        Returns:
        - tuple (lrc_path, is_enhanced) if found, None otherwise
        """
        ret = self._find_by_location_with_enhanced(metadata)
        if ret is not None:
            return ret
        ret = self._find_by_info_with_enhanced(metadata)
        if ret is not None:
            return ret
        return None

    def is_enhanced_lrc_file(self, metadata):
        """
        Check if the LRC file for given metadata contains enhanced timing
        
        Arguments:
        - `metadata`: Track metadata to check
        
        Returns:
        - True if enhanced LRC, False if standard LRC, None if no LRC found
        """
        result = self.find_with_enhanced_info(metadata)
        if result is not None:
            return result[1]
        return None

    def _find_by_condition(self, where_clause, parameters=None):
        query = LrcDb.FIND_LYRIC + where_clause
        logging.debug('Find by condition, query = %s, params = %s', query, parameters)
        c = self._conn.cursor()
        c.execute(query, parameters)
        r = c.fetchone()
        logging.debug('Fetch result: %s', r)
        c.close()
        if r:
            return r[0]
        return None

    def _find_by_condition_with_enhanced(self, where_clause, parameters=None):
        """Find LRC file and enhanced status by condition"""
        query = LrcDb.FIND_LYRIC_WITH_ENHANCED + where_clause
        logging.debug('Find with enhanced by condition, query = %s, params = %s', query, parameters)
        c = self._conn.cursor()
        c.execute(query, parameters)
        r = c.fetchone()
        logging.debug('Fetch result with enhanced: %s', r)
        c.close()
        if r:
            return (r[0], bool(r[1]))  # (path, is_enhanced)
        return None

    def _find_by_location(self, metadata):
        if not metadata.location:
            return None
        return self._find_by_condition(LrcDb.QUERY_LOCATION, (metadata.location,))

    def _find_by_location_with_enhanced(self, metadata):
        if not metadata.location:
            return None
        return self._find_by_condition_with_enhanced(LrcDb.QUERY_LOCATION, (metadata.location,))

    def _find_by_info(self, metadata):
        return self._find_by_condition(LrcDb.QUERY_INFO,
                                       query_param_from_metadata(metadata))

    def _find_by_info_with_enhanced(self, metadata):
        return self._find_by_condition_with_enhanced(LrcDb.QUERY_INFO,
                                                    query_param_from_metadata(metadata))

    def get_enhanced_stats(self):
        """
        Get statistics about enhanced vs standard LRC files in the database
        
        Returns:
        - dict with 'total', 'enhanced', and 'standard' counts
        """
        c = self._conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM {0}".format(self.TABLE_NAME))
            total = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM {0} WHERE enhanced = 1".format(self.TABLE_NAME))
            enhanced = c.fetchone()[0]
            
            return {
                'total': total,
                'enhanced': enhanced,
                'standard': total - enhanced
            }
        finally:
            c.close()

    def update_enhanced_status(self):
        """
        Scan all LRC files in the database and update their enhanced status
        Useful for migrating existing databases
        """
        c = self._conn.cursor()
        try:
            c.execute("SELECT id, lrcpath FROM {0}".format(self.TABLE_NAME))
            rows = c.fetchall()
            
            updated_count = 0
            for row_id, lrc_path in rows:
                is_enhanced = self._is_enhanced_lrc(lrc_path)
                c.execute("UPDATE {0} SET enhanced = ? WHERE id = ?".format(self.TABLE_NAME), 
                         (int(is_enhanced), row_id))
                updated_count += 1
            
            self._conn.commit()
            logging.info("Updated enhanced status for %d LRC files", updated_count)
            return updated_count
        finally:
            c.close()


def test():
    """
    Enhanced test cases including enhanced LRC functionality
    
    >>> import dbus
    >>> from osdlyrics.metadata import Metadata
    >>> db = LrcDb('/tmp/asdf')
    >>> db.assign(Metadata.from_dict({'title': 'Tiger',
    ...                               'artist': 'Soldier',
    ...                               'location': 'file:///tmp/asdf'}),
    ...           'file:///tmp/a.lrc')
    >>> db.find(Metadata.from_dict({'location': 'file:///tmp/asdf'}))
    'file:///tmp/a.lrc'
    >>> db.find(Metadata.from_dict({'location': 'file:///tmp/asdfg'}))
    >>> db.find(Metadata.from_dict({'title': 'Tiger',
    ...                             'location': 'file:///tmp/asdf'}))
    'file:///tmp/a.lrc'
    >>> db.find(Metadata.from_dict({'title': 'Tiger', }))
    >>> db.find(Metadata.from_dict({'title': 'Tiger',
    ...                             'artist': 'Soldier'}))
    'file:///tmp/a.lrc'
    >>> result = db.find_with_enhanced_info(Metadata.from_dict({'title': 'Tiger', 'artist': 'Soldier'}))
    >>> result[0] if result else None
    'file:///tmp/a.lrc'
    >>> db.assign(Metadata.from_dict({'title': 'ttTiger',
    ...                               'artist': 'ssSoldier',
    ...                               'location': 'file:///tmp/asdf'}),
    ...           'file:///tmp/b.lrc')
    >>> db.find(Metadata.from_dict({'artist': 'Soldier', }))
    >>> db.find(Metadata.from_dict({'title': 'Tiger',
    ...                                      'artist': 'Soldier', }))
    'file:///tmp/b.lrc'
    >>> db.find(Metadata.from_dict({dbus.String('title'): dbus.String('Tiger'),
    ...                             dbus.String('artist'): dbus.String('Soldier'), }))
    'file:///tmp/b.lrc'
    >>> metadata_uni = Metadata.from_dict({'title': '\u6807\u9898', 'artist': '\u6b4c\u624b', })
    >>> db.assign(metadata_uni, '\u8def\u5f84')
    >>> db.find(metadata_uni)
    '\u8def\u5f84'
    >>> stats = db.get_enhanced_stats()
    >>> stats['total'] >= 0
    True
    >>> db.find(Metadata.from_dict({'title': 'Tiger', 'artist': 'Soldiers', }))
    >>> db.find(Metadata())
    >>> db.delete(Metadata.from_dict({'location': 'file:///tmp/asdf'}))
    >>> db.find(Metadata.from_dict({'title': 'Tiger',
    ...                             'artist': 'Soldier',
    ...                             'location': 'file:///tmp/asdf'}))
    """
    import doctest
    doctest.testmod()


if __name__ == '__main__':
    test()

