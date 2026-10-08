from pathlib import Path
from jinja2 import Environment,FileSystemLoader,StrictUndefined
class PromptLoader:
    def __init__(self,base_dir:Path|None=None):
        self.base_dir=base_dir or Path(__file__).parent/'templates'; self.env=Environment(loader=FileSystemLoader(str(self.base_dir)),undefined=StrictUndefined,autoescape=False)
    def render(self,template:str,**kwargs)->str: return self.env.get_template(template).render(**kwargs)
