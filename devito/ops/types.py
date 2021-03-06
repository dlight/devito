import numpy as np
import sympy

import devito.types.basic as basic

from devito.tools import dtype_to_cstr
from devito.ops.utils import namespace


class Array(basic.Array):

    @property
    def _C_typedata(self):
        if isinstance(self.dtype, str):
            return self.dtype

        return super()._C_typedata


class OpsAccessible(basic.Symbol):
    """
    OPS accessible symbol

    Parameters
    ----------
    name : str
        Name of the symbol.
    dtype : data-type, optional
        Any object that can be interpreted as a numpy data type. Defaults
        to ``np.float32``.
    """
    is_Scalar = True

    def __new__(cls, name, dtype, read_only, *args, **kwargs):
        obj = basic.Symbol.__new__(cls, name, dtype, *args, **kwargs)
        obj.__init__(name, dtype, read_only, *args, **kwargs)
        return obj

    def __init__(self, name, dtype, read_only, *args, **kwargs):
        self.read_only = read_only
        super().__init__(name, dtype, *args, **kwargs)

    @property
    def _C_name(self):
        return self.name

    @property
    def _C_typename(self):
        return '%sACC<%s> &' % (
            'const ' if self.read_only else '',
            dtype_to_cstr(self.dtype)
        )

    @property
    def _C_typedata(self):
        return 'ACC<%s>' % dtype_to_cstr(self.dtype)


class OpsAccess(basic.Basic, sympy.Basic):
    """
    A single OPS access. The stencil of a given base (generated by to_ops_stencil) is the
    union of all its accesses.

    Parameters
    ----------
    base : OpsAccessible
        Symbol to access
    indices: list of sympy.Integer
        Indices to access
    """

    def __init__(self, base, indices, *args, **kwargs):
        self.base = base
        self.indices = indices
        super().__init__(*args, **kwargs)

    def _hashable_content(self):
        return (self.base, ','.join([str(i) for i in self.indices]))

    @property
    def function(self):
        return self.base.function

    @property
    def dtype(self):
        return self.base.dtype

    @property
    def _C_name(self):
        return "%s(%s)" % (
            self.base._C_name,
            ", ".join([str(i) for i in self.indices])
        )

    @property
    def _C_typename(self):
        return self.base._C_typename

    @property
    def _C_typedata(self):
        return self.base._C_typedata

    @property
    def args(self):
        return (self.base,)

    def __str__(self):
        return "%s(%s)" % (
            self.base.name,
            ", ".join([str(i) for i in self.indices])
        )

    def as_coeff_Mul(self):
        return sympy.S.One, self

    def as_coeff_Add(self):
        return sympy.S.Zero, self

    __repr__ = __str__


class OpsStencil(basic.LocalObject):

    def __init__(self, name, *args, **kwargs):
        super().__init__(name, np.void, *args, **kwargs)

    @property
    def _C_typename(self):
        return namespace['ops_stencil_type']


class OpsBlock(basic.Symbol):

    def __init__(self, name, *args, **kwargs):
        super().__init__(name, np.void, *args, **kwargs)

    @property
    def _C_typedata(self):
        return namespace['ops_block_type']


class OpsDat(basic.LocalObject):

    def __init__(self, name, *args, **kwargs):
        super().__init__(name, np.void, *args, **kwargs)

    @property
    def _C_typename(self):
        return namespace['ops_dat_type']
