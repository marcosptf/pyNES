import compiler
import ast
from re import match
from inspect import getmembers

import pynes.bitbag

from pynes.bitbag import Joypad, HardSprite

class BitArray:
    def __init__(self, lst):
        self.value = []
        for l in lst:
            self.value.append(l.n)

    def list(self):
        return self.value

    def to_asm(self):
        hexes = ["$%02X" % v for v in self.value]
        asm = ''
        for i in range(len(hexes) / 16):
            asm += '  .db ' + ','.join(hexes[i*16:i*16+16]) + '\n'
        if len(asm) > 0:
            return asm
        return False

class Cartridge:

    def __init__(self):
        self._state = 'prog'
        self._asm_chunks = {}

        self.has_reset = False #reset def is found
        self.has_nmi = False #nmi def is found

        self.has_prog = False #has any program
        self.has_bank1 = False #has any attrib def
        self.has_chr = False #has any sprite

        self._header = {'.inesprg':1, '.ineschr':1,
            '.inesmap':0, '.inesmir':1}
        self.sprites = []
        self.nametable = {}
        self._vars = {}
        self.bitpaks = {}
        self._joypad1 = False

    def __add__(self, other):
        if other and isinstance(other, str):
            if self._state not in self._asm_chunks:
                self._asm_chunks[self._state] = other
            else:
                self._asm_chunks[self._state] += other
        return self

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
        self.prog = value + ':\n' 

    def headers(self):
        asm_code = ""
        for h in ['.inesprg', '.ineschr', '.inesmap', '.inesmir']:
            asm_code += h + ' ' + str(self._header[h]) + '\n'
        asm_code += '\n'
        return asm_code

    def boot(self):
        asm_code = "  .org $FFFA\n"
        if self.has_nmi:
            asm_code += '  .dw NMI\n'
        else:
            asm_code += '  .dw 0\n'
        
        if self.has_reset:
            asm_code += '  .dw RESET\n'
        else:
            asm_code += '  .dw 0\n'
        
        asm_code += '  .dw 0\n\n'

        return asm_code

    def init(self):
        return (
          '  SEI          ; disable IRQs\n' +
          '  CLD          ; disable decimal mode\n' +
          '  LDX #$40\n' +
          '  STX $4017    ; disable APU frame IRQ\n' +
          '  LDX #$FF\n' +
          '  TXS          ; Set up stack\n' +
          '  INX          ; now X = 0\n' +
          '  STX $2000    ; disable NMI\n' +
          '  STX $2001    ; disable rendering\n' +
          '  STX $4010    ; disable DMC IRQs\n'
        )

    def rsset(self):
        asm_code = ""
        for v in self._vars:
            if isinstance(self._vars[v], int):
                asm_code += v + ' .rs ' + str(self._vars[v]) + '\n'
        if len(asm_code) > 0:
            return ("  .rsset $0000\n" + asm_code + '\n\n')
        return ""

    def prog(self):
        asm_code = ""
        for bp in self.bitpaks:
            asm_code += self.bitpaks[bp].procedure() + '\n'
        if 'prog' in self._asm_chunks:
            asm_code += self._asm_chunks['prog'] 
        if len(asm_code) > 0:
            return ("  .bank 0\n  .org $C000\n\n" + asm_code + '\n\n')
        return ""

    def bank1(self):
        asm_code = ""
        for v in self._vars:
            if isinstance(self._vars[v], BitArray) and self._vars[v].to_asm():
                asm_code += v + ':\n' +self._vars[v].to_asm()
        if len(asm_code) > 0:
            return ("  .bank 1\n  .org $E000\n\n" + asm_code + '\n\n')
        return ""

    def nmi(self):
        joypad_1 = Joypad(1, self)
        joypad_2 = Joypad(2, self)
        joypad_code = ''
        if joypad_1.is_used:
            joypad_code += joypad_1.to_asm()
        if len(joypad_code) > 0:
            nmi_code = (
                "NMI:\n"
                "  LDA #$00\n"
                "  STA $2003 ; Write Only: Sets the offset in sprite ram.\n"
                "  LDA #$02\n"
                "  STA $4014 ; Write Only; DMA\n"
            )
            return nmi_code + joypad_code + "\n"
        return ""

    def set_var(self, varname, value):
        self._vars[varname] = value

    def get_var(self, varname):
        return self._vars[varname]

    def to_asm(self):
        asm_code = ';Generated by PyNES\n\n'
        asm_code += self.headers()
        asm_code += self.rsset()
        asm_code += self.prog()
        asm_code += self.nmi()
        asm_code += self.bank1()
        asm_code += self.boot()

        print asm_code
        return asm_code


class PyNesVisitor(ast.NodeVisitor):

    def __init__(self):
        self.stack = []
        self.pile = []

    def generic_visit(self, node, debug = False):
        for field, value in reversed(list(ast.iter_fields(node))):
            if debug:
                print value
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        if debug:
                            print item
                        self.pile.append(self.stack)
                        self.stack = []
                        self.visit(item)
            elif isinstance(value, ast.AST):
                self.visit(value)

    def visit_Import(self, node):
        pass

    def visit_If(self, node):
        if node.test.comparators[0].s == '__main__':
            pass
        else:
            print 'IF'
            print dir(node.test.comparators[0])
            print node.test.comparators[0].s

    def visit_AugAssign(self, node):
        self.generic_visit(node)
        if len(self.stack) == 4:
            if (isinstance(self.stack[0], int) and
                isinstance(self.stack[1], str) and #TODO op
                isinstance(self.stack[2], HardSprite) and
                isinstance(self.stack[3], str)): #TODO how to check
                address = getattr(self.stack[2], self.stack[3])
                global cart
                cart += '  LDA $%04x\n' % address
                cart += '  CLC\n'
                cart += '  ADC #%d\n' % self.stack[0]
                cart += '  STA $%04x\n' % address

    def visit_Assign(self, node):
        global cart
        if (len(node.targets) == 1):
            if isinstance(node.value, ast.Call):
                varname = node.targets[0].id
                call = node.value
                if call.func.id:
                    if call.func.id == 'rs':
                        arg = call.args[0].n
                        cart.set_var(varname, arg)
                elif call.func.value.id == 'pynes' \
                    and node.value.func.attr == 'rsset':
                        #print 'opa rsset'
                        pass
            elif isinstance(node.value, ast.List):
                varname = node.targets[0].id
                cart.set_var(varname, BitArray(node.value.elts))
            elif 'ctx' in dir(node.targets[0]): #TODO fix this please
                self.generic_visit(node)
                if len(self.pile[-1]) == 1 and isinstance(self.pile[-1][0], int):
                    cart += '  LDA #%d\n' % self.pile.pop()[0]
                if len(self.stack) == 2:
                    address = getattr(self.stack[0], self.stack[1])
                    cart += '  STA $%04x\n' % address
        else:
            raise Exception('dammit')



    def visit_Attribute(self, node):
        self.generic_visit(node)
        attrib = node.attr
        self.stack.append(attrib)

    def visit_FunctionDef(self, node):
        global cart
        if node.name in ['reset','nmi']:
            cart._state = node.name
            cart += node.name.upper() + ':\n'
            if node.name == 'reset':
                cart.has_reset = True
                cart += cart.init()
            elif node.name == 'nmi':
                cart.has_nmi = True
            self.generic_visit(node)
        elif  match('^joypad[12]_(a|b|select|start|up|down|left|right)', node.name):
            cart._state = node.name
            cart.has_nmi = True
            self.generic_visit(node)

    def visit_Call(self, node):
        global cart
        if node.func.id:
            if node.func.id not in cart.bitpaks:
                obj = getattr(pynes.bitbag, node.func.id, None)
                if (obj):
                    bp = obj()
                    cart.bitpaks[node.func.id] = bp
                    self.stack.append(bp())
                    cart += bp.asm()
            else:
                bp = cart.bitpaks[node.func.id]
                self.stack.append(bp())
                cart += bp.asm()
        elif node.func.value.id == 'pynes':
            if node.func.attr == 'wait_vblank':
                print 'wait_vblank'
            elif node.func.attr == 'load_sprite':
                print 'load_sprite'

    def visit_Add(self, node):
        self.stack.append('+')

    def visit_Sub(self, node):
        print node

    def visit_BinOp(self, node):
        if (isinstance(node.left, ast.Num) and
            isinstance(node.right, ast.Num)):
            a = node.left.n
            b = node.right.n
            self.stack.append(a + b)
        else:
            self.generic_visit(node)

    def visit_Num(self, node):
        self.stack.append(node.n)

    def visit_Name(self, node):
        print node.id + 'oi'

cart = None

def pynes_compiler(code, cartridge = cart):
    global cart
    if cartridge == None:
        cart = cartridge = Cartridge()

    python_land = ast.parse(code)
    turist = PyNesVisitor()
    turist.visit(python_land)
    cart = None
    return cartridge