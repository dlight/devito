from devito.operator import *
from sympy import Eq
from devito.interfaces import TimeData, DenseData, PointData
from sympy import Function, symbols, as_finite_diff, Wild, IndexedBase
from sympy.abc import x, y, t, z
from sympy import solve, Matrix


class SourceLike(PointData):
    """Defines the behaviour of sources and receivers.
    """
    def __init__(self, *args, **kwargs):
        self.orig_data = kwargs.get('data')
        self.dt = kwargs.get('dt')
        self.h = kwargs.get('h')
        self.ndim = kwargs.get('ndim')
        self.nbpml = kwargs.get('nbpml')
        PointData.__init__(self, *args, **kwargs)
        x1, y1, z1, x2, y2, z2 = symbols('x1, y1, z1, x2, y2, z2')
        if self.ndim == 2:
            A = Matrix([[1, x1, z1, x1*z1],
                        [1, x1, z2, x1*z2],
                        [1, x2, z1, x2*z1],
                        [1, x2, z2, x2*z2]])
            self.increments = (0, 0), (0, 1), (1, 0), (1, 1)
            self.rs = symbols('rx, rz')
            rx, rz = self.rs
            p = Matrix([[1],
                        [rx],
                        [rz],
                        [rx*rz]])
        else:
            A = Matrix([[1, x1, y1, z1, x1*y1, x1*z1, y1*z1, x1*y1*z1],
                        [1, x1, y2, z1, x1*y2, x1*z1, y2*z1, x1*y2*z1],
                        [1, x2, y1, z1, x2*y1, x2*z1, y2*z1, x2*y1*z1],
                        [1, x1, y1, z2, x1*y1, x1*z2, y1*z2, x1*y1*z2],
                        [1, x2, y2, z1, x2*y2, x2*z1, y2*z1, x2*y2*z1],
                        [1, x1, y2, z2, x1*y2, x1*z2, y2*z2, x1*y2*z2],
                        [1, x2, y1, z2, x2*y1, x2*z2, y1*z2, x2*y1*z2],
                        [1, x2, y2, z2, x2*y2, x2*z2, y2*z2, x2*y2*z2]])
            self.increments = (0, 0, 0), (0, 1, 0), (1, 0, 0), (0, 0, 1), (1, 1, 0), (0, 1, 1), (1, 0, 1), (1, 1, 1)
            self.rs = symbols('rx, ry, rz')
            rx, ry, rz = self.rs
            p = Matrix([[1],
                        [rx],
                        [ry],
                        [rz],
                        [rx*ry],
                        [rx*rz],
                        [ry*rz],
                        [rx*ry*rz]])

        # Map to reference cell
        reference_cell = [(x1, 0),
                          (y1, 0),
                          (z1, 0),
                          (x2, self.h),
                          (y2, self.h),
                          (z2, self.h)]
        A = A.subs(reference_cell)
        self.bs = A.inv().T.dot(p)

    def point2grid(self, pt_coords):
        # In: s - Magnitude of the source
        #     x, z - Position of the source
        # Returns: (i, k) - Grid coordinate at top left of grid cell.
        #          (s11, s12, s21, s22) - source values at coordinates
        #          (i, k), (i, k+1), (i+1, k), (i+1, k+1)
        if self.ndim == 2:
            rx, rz = self.rs
        else:
            rx, ry, rz = self.rs
        x, y, z = pt_coords
        i = int(x/self.h)
        k = int(z/self.h)
        coords = (i + self.nbpml, k + self.nbpml)
        subs = []
        x = x - i*self.h
        subs.append((rx, x))
        if self.ndim == 3:
            j = int(y/self.h)
            y = y - j*self.h
            subs.append((ry, y))
            coords = (i + self.nbpml, j + self.nbpml, k + self.nbpml)
        z = z - k*self.h
        subs.append((rz, z))
        s = [b.subs(subs).evalf() for b in self.bs]
        return coords, tuple(s)

    # Interpolate onto receiver point.
    def grid2point(self, u, pt_coords):
        if self.ndim == 2:
            rx, rz = self.rs
        else:
            rx, ry, rz = self.rs
        x, y, z = pt_coords
        i = int(x/self.h)
        k = int(z/self.h)

        x = x - i*self.h
        z = z - k*self.h

        subs = []
        subs.append((rx, x))

        if self.ndim == 3:
            j = int(y/self.h)
            y = y - j*self.h
            subs.append((ry, y))
        subs.append((rz, z))
        if self.ndim == 2:
            return sum([b.subs(subs) * u.indexed[t, i+inc[0]+self.nbpml, k+inc[1]+self.nbpml] for inc, b in zip(self.increments, self.bs)])
        else:
            return sum([b.subs(subs) * u.indexed[t, i+inc[0]+self.nbpml, j+inc[1]+self.nbpml, k+inc[2]+self.nbpml] for inc, b in zip(self.increments, self.bs)])

    def read(self, u):
        eqs = []
        for i in range(self.npoint):
            eqs.append(Eq(self.indexed[t, i], self.grid2point(u, self.orig_data[i, :])))
        return eqs

    def add(self, m, u):
        assignments = []
        dt = self.dt
        for j in range(self.npoint):
            add = self.point2grid(self.orig_data[j, :])
            coords = add[0]
            s = add[1]
            assignments += [Eq(u.indexed[tuple([t] + [coords[i] + inc[i] for i in range(self.ndim)])],
                               u.indexed[tuple([t] + [coords[i] + inc[i] for i in range(self.ndim)])] + self.indexed[t, j]*dt*dt/m.indexed[coords]*w) for w, inc in zip(s, self.increments)]
        filtered = [x for x in assignments if isinstance(x, Eq)]
        return filtered


class FWIOperator(Operator):
    def _init_taylor(self, dim=2, time_order=2, space_order=2):
        # Only dim=2 and dim=3 are supported
        # The acoustic wave equation for the square slowness m and a source q
        # is given in 3D by :
        #
        # \begin{cases} &m \frac{d^2 u(x,t)}{dt^2} - \nabla^2 u(x,t) =q  \\
        # &u(.,0) = 0 \\ &\frac{d u(x,t)}{dt}|_{t=0} = 0 \end{cases}
        #
        # with the zero initial conditons to guarantee unicity of the solution
        # Choose dimension (2 or 3)

        # half width for indexes, goes from -half to half
        width_t = int(time_order/2)
        width_h = int(space_order/2)
        p = Function('p')
        s, h = symbols('s h')
        if dim == 2:
            m = IndexedBase("M")[x, z]
            e = IndexedBase("E")[x, z]
            solvep = p(x, z, t + width_t*s)
            solvepa = p(x, z, t - width_t*s)
        else:
            m = IndexedBase("M")[x, y, z]
            e = IndexedBase("E")[x, y, z]
            solvep = p(x, y, z, t + width_t*s)
            solvepa = p(x, y, z, t - width_t*s)

        # Indexes for finite differences
        # Could the next three list comprehensions be merged into one?
        indx = [(x + i * h) for i in range(-width_h, width_h + 1)]
        indy = [(y + i * h) for i in range(-width_h, width_h + 1)]
        indz = [(z + i * h) for i in range(-width_h, width_h + 1)]
        indt = [(t + i * s) for i in range(-width_t, width_t + 1)]

        # Time and space  discretization as a Taylor expansion.
        #
        # The time discretization is define as a second order ( $ O (dt^2)) $)
        # centered finite difference to get an explicit Euler scheme easy to
        # solve by steping in time.
        #
        # $ \frac{d^2 u(x,t)}{dt^2} \simeq \frac{u(x,t+dt) - 2 u(x,t) +
        # u(x,t-dt)}{dt^2} + O(dt^2) $
        #
        # And we define the space discretization also as a Taylor serie, with
        # oder chosen by the user. This can either be a direct expansion of the
        # second derivative bulding the laplacian, or a combination of first
        # oder space derivative. The second option can be a better choice in
        # case you would want to extand the method to more complex wave
        # equations involving first order derivatives in chain only.
        #
        # $ \frac{d^2 u(x,t)}{dt^2} \simeq \frac{1}{dx^2} \sum_k \alpha_k
        # (u(x+k dx,t)+u(x-k dx,t)) + O(dx^k)
        # Finite differences
        if dim == 2:
            dtt = as_finite_diff(p(x, z, t).diff(t, t), indt)
            dxx = as_finite_diff(p(x, z, t).diff(x, x), indx)
            dzz = as_finite_diff(p(x, z, t).diff(z, z), indz)
            dt = as_finite_diff(p(x, z, t).diff(t), indt)
            lap = dxx + dzz
        else:
            dtt = as_finite_diff(p(x, y, z, t).diff(t, t), indt)
            dxx = as_finite_diff(p(x, y, z, t).diff(x, x), indx)
            dyy = as_finite_diff(p(x, y, z, t).diff(y, y), indy)
            dzz = as_finite_diff(p(x, y, z, t).diff(z, z), indz)
            dt = as_finite_diff(p(x, y, z, t).diff(t), indt)
            lap = dxx + dyy + dzz

        wave_equation = m*dtt - lap + e*dt
        stencil = solve(wave_equation, solvep)[0]
        wave_equationA = m*dtt - lap - e*dt
        stencilA = solve(wave_equationA, solvepa)[0]
        return ((stencil, (m, s, h, e)), (stencilA, (m, s, h, e)))

    @classmethod
    def smart_sympy_replace(cls, num_dim, time_order, expr, fun, arr, fw):
        a = Wild('a')
        b = Wild('b')
        c = Wild('c')
        d = Wild('d')
        f = Wild('f')
        q = Wild('q')
        x, y, z = symbols("x y z")
        h, s, t = symbols("h s t")
        width_t = int(time_order/2)
        # Replace function notation with array notation
        # Reorder indices so time comes first
        if num_dim == 2:
            # Replace function notation with array notation
            res = expr.replace(fun(a, b, c), arr.indexed[a, b, c])
            # Reorder indices so time comes first
            res = res.replace(arr.indexed[x+b, z+d, t+f], arr.indexed[t+f, x+b, z+d])
        if num_dim == 3:
            res = expr.replace(fun(a, b, c, d), arr.indexed[a, b, c, d])
            res = res.replace(arr.indexed[x+b, y+q, z+d, t+f], arr.indexed[t+f, x+b, y+q, z+d])
        # Replace x+h in indices with x+1
        for dim_var in [x, y, z]:
            res = res.replace(dim_var+c*h, dim_var+c)
        # Replace t+s with t+1
        res = res.replace(t+c*s, t+c)
        if fw:
            res = res.subs({t: t-width_t})
        else:
            res = res.subs({t: t+width_t})
        return res

    def total_dim(self, ndim):
        if ndim == 2:
            return (t, x, z)
        else:
            return (t, x, y, z)

    def space_dim(self, ndim):
        if ndim == 2:
            return (x, z)
        else:
            return (x, y, z)


class ForwardOperator(FWIOperator):
    def __init__(self, m, src, damp, rec, u, time_order=4, spc_order=12, **kwargs):
        assert(m.shape == damp.shape)
        input_params = [m, src, damp, rec, u]
        u.pad_time = False
        output_params = []
        dim = len(m.shape)
        total_dim = self.total_dim(dim)
        space_dim = self.space_dim(dim)
        stencil, subs = self._init_taylor(dim, time_order, spc_order)[0]
        stencil = self.smart_sympy_replace(dim, time_order, stencil, Function('p'), u, fw=True)
        stencil_args = [m.indexed[space_dim], src.dt, src.h, damp.indexed[space_dim]]
        main_stencil = Eq(u.indexed[total_dim], stencil)
        stencils = [(main_stencil, stencil_args)]
        src_list = src.add(m, u)
        rec = rec.read(u)
        self.time_loop_stencils_post = src_list+rec
        super(ForwardOperator, self).__init__(subs, src.nt, m.shape, spc_border=spc_order/2,
                                              time_order=time_order, forward=True, dtype=m.dtype,
                                              stencils=stencils, input_params=input_params,
                                              output_params=output_params, **kwargs)


class AdjointOperator(FWIOperator):
    def __init__(self, m, rec, damp, srca, time_order=4, spc_order=12, **kwargs):
        assert(m.shape == damp.shape)
        input_params = [m, rec, damp, srca]
        v = TimeData(name="v", shape=m.shape, time_dim=rec.nt, time_order=time_order,
                     save=True, dtype=m.dtype)
        output_params = [v]
        dim = len(m.shape)
        total_dim = self.total_dim(dim)
        space_dim = self.space_dim(dim)
        lhs = v.indexed[total_dim]
        stencil, subs = self._init_taylor(dim, time_order, spc_order)[1]
        stencil = self.smart_sympy_replace(dim, time_order, stencil, Function('p'), v, fw=False)
        main_stencil = Eq(lhs, stencil)
        stencil_args = [m.indexed[space_dim], rec.dt, rec.h, damp.indexed[space_dim]]
        stencils = [(main_stencil, stencil_args)]
        rec_list = rec.add(m, v)
        src_list = srca.read(v)
        self.time_loop_stencils_post = rec_list + src_list
        super(AdjointOperator, self).__init__(subs, rec.nt, m.shape, spc_border=spc_order/2,
                                              time_order=time_order, forward=False, dtype=m.dtype,
                                              stencils=stencils, input_params=input_params,
                                              output_params=output_params, **kwargs)


class GradientOperator(FWIOperator):
    def __init__(self, u, m, rec, damp, time_order=4, spc_order=12, **kwargs):
        assert(m.shape == damp.shape)
        input_params = [u, m, rec, damp]
        v = TimeData(name="v", shape=m.shape, time_dim=rec.nt, time_order=time_order,
                     save=False, dtype=m.dtype)
        grad = DenseData(name="grad", shape=m.shape, dtype=m.dtype)
        output_params = [grad, v]
        dim = len(m.shape)
        total_dim = self.total_dim(dim)
        space_dim = self.space_dim(dim)
        lhs = v.indexed[total_dim]
        stencil, subs = self._init_taylor(dim, time_order, spc_order)[1]
        stencil = self.smart_sympy_replace(dim, time_order, stencil, Function('p'), v, fw=False)
        stencil_args = [m.indexed[space_dim], rec.dt, rec.h, damp.indexed[space_dim]]
        main_stencil = Eq(lhs, lhs + stencil)
        gradient_update = Eq(grad.indexed[space_dim], grad.indexed[space_dim] -
                             (v.indexed[total_dim] - 2 * v.indexed[tuple((t + 1,) + space_dim)] +
                              v.indexed[tuple((t + 2,) + space_dim)]) * u.indexed[total_dim])
        reset_v = Eq(v.indexed[tuple((t + 2,) + space_dim)], 0)
        stencils = [(main_stencil, stencil_args), (gradient_update, []), (reset_v, [])]

        rec_list = rec.add(m, v)
        self.time_loop_stencils_pre = rec_list
        super(GradientOperator, self).__init__(subs, rec.nt, m.shape, spc_border=spc_order/2,
                                               time_order=time_order, forward=False, dtype=m.dtype,
                                               stencils=stencils, input_params=input_params,
                                               output_params=output_params, **kwargs)


class BornOperator(FWIOperator):
    def __init__(self, dm, m, src, damp, rec, time_order=4, spc_order=12, **kwargs):
        assert(m.shape == damp.shape)
        input_params = [dm, m, src, damp, rec]
        u = TimeData(name="u", shape=m.shape, time_dim=src.nt, time_order=time_order,
                     save=False, dtype=m.dtype)
        U = TimeData(name="U", shape=m.shape, time_dim=src.nt, time_order=time_order,
                     save=False, dtype=m.dtype)
        output_params = [u, U]
        dim = len(m.shape)
        total_dim = self.total_dim(dim)
        space_dim = self.space_dim(dim)
        dt = src.dt
        h = src.h
        src_list = src.add(m, u)
        rec = rec.read(U)
        self.time_loop_stencils_pre = src_list
        self.time_loop_stencils_post = rec
        stencil, subs = self._init_taylor(dim, time_order, spc_order)[0]
        first_stencil = self.smart_sympy_replace(dim, time_order, stencil, Function('p'), u, fw=True)
        second_stencil = self.smart_sympy_replace(dim, time_order, stencil, Function('p'), U, fw=True)
        first_stencil_args = [m.indexed[space_dim], dt, h, damp.indexed[space_dim]]
        first_update = Eq(u.indexed[total_dim], u.indexed[total_dim]+first_stencil)
        src2 = -(dt**-2)*(u.indexed[total_dim]-2*u.indexed[tuple((t - 1,) + space_dim)]+u.indexed[tuple((t - 2,) + space_dim)])*dm.indexed[space_dim]
        second_stencil_args = [m.indexed[space_dim], dt, h, damp.indexed[space_dim]]
        second_update = Eq(U.indexed[total_dim], second_stencil)
        insert_second_source = Eq(U.indexed[total_dim], U.indexed[total_dim]+(dt*dt)/m.indexed[space_dim]*src2)
        reset_u = Eq(u.indexed[tuple((t - 2,) + space_dim)], 0)
        stencils = [(first_update, first_stencil_args), (second_update, second_stencil_args),
                    (insert_second_source, []), (reset_u, [])]
        super(BornOperator, self).__init__(subs, src.nt, m.shape, spc_border=spc_order/2,
                                           time_order=time_order, forward=True, dtype=m.dtype,
                                           stencils=stencils, input_params=input_params,
                                           output_params=output_params, **kwargs)