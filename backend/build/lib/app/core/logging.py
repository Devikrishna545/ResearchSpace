import json, logging, sys
from datetime import datetime, timezone
class JsonFormatter(logging.Formatter):
    def format(self,record):
        data={'ts':datetime.now(timezone.utc).isoformat(),'level':record.levelname,'logger':record.name,'message':record.getMessage()}
        if record.exc_info: data['exc_info']=self.formatException(record.exc_info)
        return json.dumps(data,ensure_ascii=False)
def configure_logging(level='INFO'):
    h=logging.StreamHandler(sys.stdout); h.setFormatter(JsonFormatter()); root=logging.getLogger(); root.handlers.clear(); root.addHandler(h); root.setLevel(level)
    # httpx INFO logs include the full request URL, including OpenAlex's consented mailto parameter.
    logging.getLogger('httpx').setLevel(logging.WARNING)
