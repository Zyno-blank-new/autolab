"""Optional small pinned HTTPS data downloads from operator-allowlisted URLs."""
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import hashlib
from autolab.preparation.models import PreparationError
from .base import Artifact, MAX_BYTES, SAFE_SUFFIXES, require_keys


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise PreparationError('Download redirects require separate explicit approval')


class DownloadHandler:
    def prepare(self, requirement, context):
        p=requirement.parameters
        require_keys(p, {'url','sha256','license'}, {'url','sha256'})
        url=p['url']; parsed=urlsplit(url)
        if (url not in context['allowed_downloads'] or parsed.scheme!='https' or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not any(parsed.path.lower().endswith(s) for s in SAFE_SUFFIXES)):
            raise PreparationError('Download is not an operator-allowlisted public HTTPS data URL')
        with build_opener(NoRedirect()).open(Request(url,headers={'User-Agent':'AutoLab-Preparation/1'}),timeout=20) as response:
            content=response.read(MAX_BYTES+1)
        if len(content)>MAX_BYTES or hashlib.sha256(content).hexdigest()!=p['sha256']:
            raise PreparationError('Download size or pinned checksum mismatch')
        return Artifact(content=content,metadata={'source_url':url,'license':p.get('license'),
            'download_execution':'none; artifact is data only'})
