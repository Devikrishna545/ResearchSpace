import re
from html.parser import HTMLParser


class _MetadataTextParser(HTMLParser):
    _blocks = {'abstract', 'br', 'div', 'p', 'sec', 'section', 'title', 'list-item'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        name = tag.rsplit(':', 1)[-1]
        if name in {'script', 'style'}:
            self.skip_depth += 1
        elif not self.skip_depth and name in self._blocks:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        name = tag.rsplit(':', 1)[-1]
        if name in {'script', 'style'} and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and name in self._blocks:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def clean_metadata_text(value: str | None) -> str | None:
    if not value:
        return None
    parser = _MetadataTextParser()
    parser.feed(value)
    return ' '.join(''.join(parser.parts).split()) or None


def normalize_title(title:str)->str: return re.sub(r'\W+',' ',title.lower()).strip()
def tokenize(text:str)->list[str]: return re.findall(r'[a-zA-Z0-9]+',text.lower())
