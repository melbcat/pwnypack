from __future__ import print_function
import argparse
import re
import six
import sys
import pwnypack.codec
import pwnypack.elf
import pwnypack.main
import pwnypack.asm
import pwnypack.target
import pwnypack.util


__all__ = [
    'find_gadget',
]


def find_gadget(elf, gadget, align=1, unique=True):
    if not isinstance(elf, pwnypack.elf.ELF):
        elf = pwnypack.elf.ELF(elf)

    matches = []
    gadgets = []

    if isinstance(gadget, six.binary_type):
        gadget = re.compile(re.escape(gadget))

    for section in elf.section_headers:
        if section['type'] != elf.SectionType.PROGBITS:
            continue

        data = elf.read_section(section)

        for match in gadget.finditer(data):
            match_index = match.start()
            if match_index % align != 0:
                continue

            match_gadget = match.group()

            if match_gadget in gadgets:
                continue

            match_addr = section['addr'] + match_index

            try:
                match_asm = pwnypack.asm.disasm(match_gadget, match_addr, elf)

                matches.append({
                    'section': section,
                    'offset': match_index,
                    'addr': match_addr,
                    'gadget': match_gadget,
                    'asm': match_asm,
                })
            except SyntaxError:
                # Prevent retrying this gadget even in non-unique mode.
                gadgets.append(match_gadget)
                continue

            if unique:
                gadgets.append(match_gadget)

    return matches


@pwnypack.main.register('gadget')
def gadget_app(_parser, cmd, args):  # pragma: no cover
    """
    Find ROP gadgets in an ELF binary.
    """

    parser = argparse.ArgumentParser(
        prog=_parser.prog,
        description=_parser.description,
    )
    parser.add_argument('file', help='ELF file to find gadgets in')
    parser.add_argument('gadget', help='the assembler source or reghex expression')
    parser.add_argument(
        '--reghex', '-r',
        dest='mode',
        action='store_const',
        const='reghex',
        help='use reghex expression (hex bytes interspaced with ? for wildcard)',
    )
    parser.add_argument(
        '--asm', '-a',
        dest='mode',
        action='store_const',
        const='asm',
        help='use assembler expression (separate lines with semi-colon)',
    )
    parser.add_argument(
        '--all', '-l',
        dest='unique',
        action='store_const',
        const=False,
        default=True,
        help='also show non-unique gadgets',
    )
    args = parser.parse_args(args)

    if args.mode is None:
        try:
            pwnypack.util.reghex(args.gadget)
            args.mode = 'reghex'
        except SyntaxError:
            args.mode = 'asm'

    if args.mode == 'reghex':
        try:
            gadget = pwnypack.util.reghex(args.gadget)
        except SyntaxError:
            print('Invalid reghex pattern.')
            sys.exit(1)
    else:
        try:
            gadget = pwnypack.asm.asm(args.gadget.replace(';', '\n'))
        except SyntaxError as e:
            print('Could not assemble:', e.msg)
            sys.exit(1)

    elf = pwnypack.elf.ELF(args.file)

    matches = find_gadget(
        elf,
        gadget,
        unique=args.unique
    )

    if not matches:
        print('No gadgets found.', file=sys.stdout)
        return

    longest_gadget = max(len(m['gadget']) for m in matches)
    fmt = '  0x%%0%dx: [ %%-%ds ] %%s' % (elf.bits / 4, longest_gadget * 3 - 1)

    current_section = None

    for match in matches:
        if match['section']['name'] != current_section:
            if current_section is not None:
                print()
            print('Section: %s' % match['section']['name'])
            current_section = match['section']['name']

        hex_gadget = pwnypack.codec.enhex(match['gadget'])
        print(fmt % (
            match['addr'],
            ' '.join(
                hex_gadget[i:i+2]
                for i in range(0, len(hex_gadget), 2)
            ),
            ' ; '.join(match['asm'])
        ))

    print()
