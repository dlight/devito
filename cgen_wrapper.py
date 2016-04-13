from cgen import *
from codeprinter import ccode

class Ternary(Generable):
    def __init__(self, condition, true_statement, false_statement):
        self.condition = ccode(condition)
        self.true_statement = ccode(true_statement)
        self.false_statement = ccode(false_statement)
    
    def generate(self):
        yield "(("+str(self.condition)+")?"+str(self.true_statement)+":"+str(self.false_statement)+")"
        