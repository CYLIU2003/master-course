"""Remove only PowerPoint double-serialization noise from six-decimal chart data."""
from decimal import Decimal
from pathlib import Path
import re
import sys
from zipfile import ZipFile


def normalize(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    def point(match):
        value = Decimal(match.group(2))
        rounded = value.quantize(Decimal('0.000001'))
        # The builder already rounded to six decimals. Larger changes are not formatting.
        if not value.is_finite() or abs(value - rounded) > Decimal('0.0000001'):
            raise ValueError('Unexpected numerical change in chart cache')
        return match.group(1) + format(rounded, 'f') + match.group(3)
    with ZipFile(source) as src, ZipFile(destination, 'x') as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if '/charts/' in item.filename and item.filename.endswith('.xml'):
                text = data.decode('utf8')
                # Only numeric chart caches/literals; titles, labels and source CSV are untouched.
                text = re.sub(r'(<c:(?:numLit|numCache)\b[^>]*>)(.*?)(</c:(?:numLit|numCache)>)',
                              lambda block: block.group(1) + re.sub(
                                  r'(<c:v>)([-+0-9.eE]+)(</c:v>)', point, block.group(2)) + block.group(3), text)
                data = text.encode('utf8')
            dst.writestr(item, data)


if __name__ == '__main__':
    normalize(Path(sys.argv[1]), Path(sys.argv[2]))
