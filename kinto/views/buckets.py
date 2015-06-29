from pyramid.httpexceptions import HTTPForbidden
from pyramid.security import NO_PERMISSION_REQUIRED
from pyramid.view import view_config

from cliquet import resource
from cliquet.utils import hmac_digest
from cliquet.views.batch import build_request

from kinto.views import NameGenerator


@view_config(route_name='default_bucket', permission=NO_PERMISSION_REQUIRED)
def default_bucket(request):
    if (not hasattr(request, 'prefixed_userid') or
            request.prefixed_userid is None):
        raise HTTPForbidden  # Pass through the forbidden_view_config

    settings = request.registry.settings
    hmac_secret = settings['cliquet.userid_hmac_secret']
    bucket_id = hmac_digest(hmac_secret, request.prefixed_userid)[:32]
    path = request.path.replace('default', bucket_id)

    # Make sure bucket exists
    # XXX: Is there a better way to do a GET or CREATE?
    subrequest = build_request(request, {
        'method': 'PUT',
        'path': '/buckets/%s' % bucket_id,
        'body': {"data": {}},
        'headers': {'If-None-Match': '*'}
    })
    request.invoke_subrequest(subrequest)

    # Make sure the collection exists
    subpath = request.matchdict['subpath']
    if subpath.startswith('/collections/'):
        # XXX: Is there a better way to do a GET or CREATE?
        collection_id = subpath.split('/')[2]
        subrequest = build_request(request, {
            'method': 'PUT',
            'path': '/buckets/%s/collections/%s' % (bucket_id, collection_id),
            'body': {"data": {}},
            'headers': {'If-None-Match': '*'}
        })
        request.invoke_subrequest(subrequest)

    subrequest = build_request(request, {
        'method': request.method,
        'path': path,
        'body': request.body
    })

    return request.invoke_subrequest(subrequest)


@resource.register(name='bucket',
                   collection_methods=('GET',),
                   collection_path='/buckets',
                   record_path='/buckets/{{id}}')
class Bucket(resource.ProtectedResource):
    permissions = ('read', 'write', 'collection:create', 'group:create')

    def __init__(self, *args, **kwargs):
        super(Bucket, self).__init__(*args, **kwargs)
        self.collection.id_generator = NameGenerator()

    def get_parent_id(self, request):
        # Buckets are not isolated by user, unlike Cliquet resources.
        return ''

    def delete(self):
        result = super(Bucket, self).delete()

        # Delete groups.
        storage = self.collection.storage
        parent_id = '/buckets/%s' % self.record_id
        storage.delete_all(collection_id='group', parent_id=parent_id)

        # Delete collections.
        deleted = storage.delete_all(collection_id='collection',
                                     parent_id=parent_id)

        # Delete records.
        id_field = self.collection.id_field
        for collection in deleted:
            parent_id = '/buckets/%s/collections/%s' % (self.record_id,
                                                        collection[id_field])
            storage.delete_all(collection_id='record', parent_id=parent_id)

        return result
