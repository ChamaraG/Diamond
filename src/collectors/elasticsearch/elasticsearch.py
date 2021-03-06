# coding=utf-8

"""
Collect the elasticsearch stats for the local node

#### Dependencies

 * urlib2

"""

import urllib2

try:
    import json
    json  # workaround for pyflakes issue #13
except ImportError:
    import simplejson as json

import diamond.collector


class ElasticSearchCollector(diamond.collector.Collector):

    def get_default_config_help(self):
        config_help = super(ElasticSearchCollector,
                            self).get_default_config_help()
        config_help.update({
            'host': "",
            'port': "",
            'stats': "Available stats: \n"
            + " - jvm (JVM information) \n"
            + " - thread_pool (Thread pool information) \n"
            + " - indices (Individual index stats)\n",
        })
        return config_help

    def get_default_config(self):
        """
        Returns the default collector settings
        """
        config = super(ElasticSearchCollector, self).get_default_config()
        config.update({
            'host':     '127.0.0.1',
            'port':     9200,
            'path':     'elasticsearch',
            'stats':    ['jvm', 'thread_pool', 'indices'],
        })
        return config

    def _get(self, path):
        url = 'http://%s:%i/%s' % (
            self.config['host'], int(self.config['port']), path)
        try:
            response = urllib2.urlopen(url)
        except urllib2.HTTPError, err:
            self.log.error("%s: %s", url, err)
            return False

        try:
            return json.load(response)
        except (TypeError, ValueError):
            self.log.error("Unable to parse response from elasticsearch as a"
                           + " json object")
            return False

    def _copy_one_level(self, metrics, prefix, data, filter=lambda key: True):
        for key, value in data.iteritems():
            if filter(key):
                metrics['%s.%s' % (prefix, key)] = value

    def _copy_two_level(self, metrics, prefix, data, filter=lambda key: True):
        for key1, d1 in data.iteritems():
            self._copy_one_level(metrics, '%s.%s' % (prefix, key1), d1, filter)

    def _index_metrics(self, metrics, prefix, index):
        if 'docs' in index:
            metrics['%s.docs.count' % prefix] = index['docs']['count']
            metrics['%s.docs.deleted' % prefix] = index['docs']['deleted']

        if 'store' in index:
            metrics['%s.datastore.size' % prefix] = index['store']['size_in_bytes']

        # publish all 'total' and 'time_in_millis' stats
        self._copy_two_level(metrics, prefix, index,
            lambda key: key.endswith('total') or key.endswith('time_in_millis'))

    def collect(self):
        if json is None:
            self.log.error('Unable to import json')
            return {}

        result = self._get('_cluster/nodes/_local/stats?all=true')
        if not result:
            return

        metrics = {}
        node = result['nodes'].keys()[0]
        data = result['nodes'][node]

        #
        # http connections to ES
        metrics['http.current'] = data['http']['current_open']

        #
        # indices
        indices = data['indices']
        metrics['indices.docs.count'] = indices['docs']['count']
        metrics['indices.docs.deleted'] = indices['docs']['deleted']

        metrics['indices.datastore.size'] = indices['store']['size_in_bytes']

        transport = data['transport']
        metrics['transport.rx.count'] = transport['rx_count']
        metrics['transport.rx.size'] = transport['rx_size_in_bytes']
        metrics['transport.tx.count'] = transport['tx_count']
        metrics['transport.tx.size'] = transport['tx_size_in_bytes']

        # elasticsearch < 0.90RC2
        if 'cache' in indices:
            cache = indices['cache']

            if 'bloom_size_in_bytes' in cache:
                metrics['cache.bloom.size'] = cache['bloom_size_in_bytes']
            if 'field_evictions' in cache:
                metrics['cache.field.evictions'] = cache['field_evictions']
            if 'field_size_in_bytes' in cache:
                metrics['cache.field.size'] = cache['field_size_in_bytes']
            metrics['cache.filter.count'] = cache['filter_count']
            metrics['cache.filter.evictions'] = cache['filter_evictions']
            metrics['cache.filter.size'] = cache['filter_size_in_bytes']
            if 'id_cache_size_in_bytes' in cache:
                metrics['cache.id.size'] = cache['id_cache_size_in_bytes']

        # elasticsearch >= 0.90RC2
        if 'filter_cache' in indices:
            cache = indices['filter_cache']

            metrics['cache.filter.evictions'] = cache['evictions']
            metrics['cache.filter.size'] = cache['memory_size_in_bytes']

            if 'count' in cache:
                metrics['cache.filter.count'] = cache['count']


        # elasticsearch >= 0.90RC2
        if 'id_cache' in indices:
            cache = indices['id_cache']

            if 'memory_size_in_bytes' in cache:
                metrics['cache.id.size'] = cache['memory_size_in_bytes']


        # elasticsearch >= 0.90
        if 'field_data' in indices:
            metrics['field_data.memory_size'] = indices['field_data'][
                'memory_size']

        #
        # process mem/cpu
        process = data['process']
        mem = process['mem']
        metrics['process.cpu.percent'] = process['cpu']['percent']
        metrics['process.mem.resident'] = mem['resident_in_bytes']
        metrics['process.mem.share'] = mem['share_in_bytes']
        metrics['process.mem.virtual'] = mem['total_virtual_in_bytes']

        #
        # filesystem
        if 'fs' in data:
            fs_data = data['fs']['data'][0]
            metrics['disk.reads.count'] = fs_data['disk_reads']
            metrics['disk.reads.size'] = fs_data['disk_read_size_in_bytes']
            metrics['disk.writes.count'] = fs_data['disk_writes']
            metrics['disk.writes.size'] = fs_data['disk_write_size_in_bytes']

        #
        # jvm
        if 'jvm' in self.config['stats']:
            jvm = data['jvm']
            mem = jvm['mem']
            for k in ('heap_used', 'heap_committed', 'non_heap_used',
                      'non_heap_committed'):
                metrics['jvm.mem.%s' % k] = mem['%s_in_bytes' % k]

            for pool, d in mem['pools'].iteritems():
                pool = pool.replace(' ', '_')
                metrics['jvm.mem.pools.%s.used' % pool] = d['used_in_bytes']
                metrics['jvm.mem.pools.%s.max' % pool] = d['max_in_bytes']

            metrics['jvm.threads.count'] = jvm['threads']['count']

            gc = jvm['gc']
            metrics['jvm.gc.collection.count'] = gc['collection_count']
            metrics['jvm.gc.collection.time'] = gc['collection_time_in_millis']
            for collector, d in gc['collectors'].iteritems():
                metrics['jvm.gc.collection.%s.count' % collector] = d[
                    'collection_count']
                metrics['jvm.gc.collection.%s.time' % collector] = d[
                    'collection_time_in_millis']

        #
        # thread_pool
        if 'thread_pool' in self.config['stats']:
            self._copy_two_level(metrics, 'thread_pool', data['thread_pool'])

        #
        # network
        self._copy_two_level(metrics, 'network', data['network'])

        if 'indices' in self.config['stats']:
            #
            # individual index stats
            result = self._get('_stats?clear=true&docs=true&store=true&'
                               + 'indexing=true&get=true&search=true')
            if not result:
                return

            _all = result['_all']
            self._index_metrics(metrics, 'indices._all', _all['primaries'])

            if 'indices' in _all:
                indices = _all['indices']
            elif 'indices' in result:          # elasticsearch >= 0.90RC2
                indices = result['indices']
            else:
                return

            for name, index in indices.iteritems():
                self._index_metrics(metrics, 'indices.%s' % name,
                                    index['primaries'])

        for key in metrics:
            self.publish(key, metrics[key])
