# -*- coding: utf8 -*-
#
#   pyrayopt - raytracing for optical imaging systems
#   Copyright (C) 2012 Robert Jordens <jordens@phys.ethz.ch>
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function, absolute_import, division

import numpy as np
from scipy.optimize import newton

from .transformations import (euler_matrix, euler_from_matrix, 
        translation_matrix, rotation_matrix, concatenate_matrices)
from .name_mixin import NameMixin
from .aberration_orders import aberration_intrinsic
from .utils import sinarctan, tanarcsin


class TransformMixin(object):
    def __init__(self, distance=0., direction=(0, 0, 1.), angles=None):
        self.update(distance, direction, angles)
        # offset = distance*direction: in lab system, relative to last
        # element (thus cumulative in lab system)
        # angles: relative to unit offset (-incidence angle)
        # excidence: excidence angles for axial ray (snell)

    @property
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, offset):
        d = np.linalg.norm(offset)
        self.update(d, offset/d, self._angles)

    @property
    def angles(self):
        return self._angles

    @angles.setter
    def angles(self, angles):
        self.update(self._distance, self._direction, angles)

    @property
    def distance(self):
        return self._distance

    @distance.setter
    def distance(self, distance):
        self.update(distance, self._direction, self._angles)

    @property
    def direction(self):
        return self._direction

    @direction.setter
    def direction(self, direction):
        self.update(self._distance, direction, self._angles)

    @property
    def incidence(self):
        # of the optical axis onto the surface
        return self.transform_to(self._direction, angle=True)

    @property
    def excidence(self, mu):
        raise NotImplementedError
        e = self.incidence * (mu, mu, 0)
        e[2] = np.sqrt(1 - np.square(e).sum())
        e = i/np.linalg.unit_vector(i)
        return e

    def aim(self, direction, mu):
        """orient such that direction is excidence"""
        e = np.array(direction)
        i = -self.direction
        r = i - mu*e # snell
        r /= np.linalg.norm(r)
        rdir = np.cross((0, 0, 1.), r)
        rang = np.arcsin(np.linalg.norm(rdir))
        if np.allclose(rdir, 0):
            rdir = (1., 0, 0)
        r = rotation_matrix(rang, rdir)
        angles = euler_from_matrix(r, "rxyz")
        self.update(self._distance, self._direction, angles)

    def update(self, distance, direction, angles):
        self._direction = u = np.array(direction)
        u /= np.linalg.norm(u)
        if distance < 0:
            u *= -1
        self._distance = d = abs(distance)
        self._offset = o = d*u
        self.normal = angles is None or np.allclose(angles, 0)
        self.straight = np.allclose(u, (0, 0, 1))
        self._angles = a = None if self.normal else np.array(angles)
        self.rotated = not (self.normal and self.straight)
        if not self.rotated:
            self.rot_axis = self.rot_normal = None
            return
        r = np.eye(3)
        if not self.straight:
            rdir = np.cross((0, 0, 1.), u)
            rang = np.arcsin(np.linalg.norm(rdir))
            if u[2] < 0: # FIXME
                rang += np.pi
            if np.allclose(rdir, 0):
                rdir = (1., 0, 0)
            self.rot_axis = r1 = rotation_matrix(rang, rdir)[:3, :3]
            r = np.dot(r, r1)
        if not self.normal:
            r1 = euler_matrix(axes="rxyz", *tuple(a))[:3, :3]
            r = np.dot(r, r1)
        self.rot_normal = r

    def _do_rotate(self, r, t, f, y):
        if f:
            if t:
                r = r.T
            y = (np.dot(yi, r) for yi in y)
        else:
            y = (yi.copy() for yi in y)
        y = tuple(y)
        if len(y) == 1:
            y = y[0]
        return y

    def from_axis(self, *y):
        return self._do_rotate(self.rot_axis, False, not self.straight, y)

    def to_axis(self, *y):
        return self._do_rotate(self.rot_axis, True, not self.straight, y)

    def from_normal(self, *y):
        return self._do_rotate(self.rot_normal, False, self.rotated, y)

    def to_normal(self, *y):
        return self._do_rotate(self.rot_normal, True, self.rotated, y)


class Element(NameMixin, TransformMixin):
    typ = "P"

    def __init__(self, radius=np.inf, finite=True,
            angular_radius=np.inf, **kwargs):
        super(Element, self).__init__(**kwargs)
        self.radius = radius
        self.finite = finite
        self.angular_radius = angular_radius
        # angular radius is tan(u) as sin(u) is ambiguous
        # sin(pi/2 + eps) = sin(pi/2 - eps)

    def to_pupil(self, yo, yp, pupil_distance, pupil_height):
        ro = self.radius if self.finite else self.angular_radius
        yo, yp, ro, rp = np.broadcast_arrays(yo, yp, ro, pupil_height)
        if self.finite:
            y = -yo*ro
            u = sinarctan((yp*rp - y)/pupil_distance)
        else:
            u = sinarctan(yo*ro)
            y = yp*rp - pupil_distance*tanarcsin(u)
        return y, u

    def from_pupil(self, y, u, pupil_distance, pupil_height):
        ro = self.radius if self.finite else self.angular_radius
        y, u, ro, rp = np.broadcast_arrays(y, u, ro, pupil_height)
        yp = (y + pupil_distance*tanarcsin(u))/rp
        if self.finite:
            yo = -y/ro
        else:
            yo = tanarcsin(y/ro)
        return yo, yp

    def intercept(self, y, u):
        # ray length to intersection with element
        # only reference plane, overridden in subclasses
        # solution for z=0
        s = -y[:, 2]/u[:, 2]
        # given angles is set correctly, mask s
        return s

    def clip(self, y, u):
        if not np.isfinite(self.radius):
            return u
        bad = np.square(y[:, :2]).sum(1) > self.radius**2
        u = np.where(bad[:, None], np.nan, u)
        return u

    def propagate_paraxial(self, yu0, n0, l):
        n, m = self.paraxial_matrix(n0, l)
        yu = np.dot(yu0, m.T)
        return yu, n

    def propagate_gaussian(self, q0i, n0, l):
        n, m = self.paraxial_matrix(n0, l)
        a, b, c, d = m[:2, :2], m[:2, 2:], m[2:, :2], m[2:, 2:]
        qi = np.dot(c + np.dot(d, q0i), np.linalg.inv(a + np.dot(b, q0i)))
        return qi, n

    def paraxial_matrix(self, n0, l):
        m = np.eye(4)
        d = self.distance
        m[0, 2] = m[1, 3] = d
        return n0, m

    def propagate(self, y0, u0, n0, l, clip=True):
        t = self.intercept(y0, u0)
        y = y0 + t[:, None]*u0
        if clip:
            u0 = self.clip(y, u0)
        n = n0
        return y, u0, n, t*n0

    def reverse(self):
        pass

    def rescale(self, scale):
        self.distance *= scale
        self.radius *= scale

    def surface_cut(self, axis, points):
        rad = self.radius if np.isfinite(self.radius) else 0.
        xyz = np.zeros((points, 3))
        xyz[:, axis] = np.linspace(-rad, rad, points)
        return xyz

    def aberration(self, *args):
        return 0

    def dispersion(self, *args):
        return 0


class Aperture(Element):
    typ = "A"

    def surface_cut(self, axis, points):
        r = self.radius if np.isfinite(self.radius) else 0.
        xyz = np.zeros((5, 3))
        xyz[:, axis] = np.array([-r*1.5, -r, np.nan, r, r*1.5])
        return xyz


class Interface(Element):
    typ = "F"

    def __init__(self, material=None, **kwargs):
        super(Interface, self).__init__(**kwargs)
        self.material = material

    def refractive_index(self, wavelength):
        return abs(self.material.refractive_index(wavelength))

    def paraxial_matrix(self, n0, l):
        n, m = super(Interface, self).paraxial_matrix(n0, l)
        if self.material is not None:
            n = self.refractive_index(l)
        return n, m

    def refract(self, y, u0, mu):
        return u0

    def propagate(self, y0, u0, n0, l, clip=True):
        t = self.intercept(y0, u0)
        y = y0 + t[:, None]*u0
        if clip:
            u0 = self.clip(y, u0)
        u = u0
        n = n0
        if self.material is not None:
            if self.material.mirror:
                mu = -1.
            else:
                n = self.refractive_index(l)
                mu = n0/n
            u = self.refract(y, u0, mu)
        return y, u, n, t*n0

    def dispersion(self, lmin, lmax):
        v = 0.
        if self.material is not None:
            v = self.material.delta_n(lmin, lmax)
        return v

    def shape_func(self, p):
        raise NotImplementedError

    def shape_func_deriv(self, p):
        raise NotImplementedError

    def intercept(self, y, u):
        s = super(Interface, self).intercept(y, u)
        for i in range(y.shape[0]):
            yi, ui, si = y[i], u[i], s[i]
            def func(si): return self.shape_func(yi + si*ui)
            def fprime(si): return np.dot(
                    self.shape_func_deriv(yi + si*ui), ui)
            try:
                s[i] = newton(func=func, fprime=fprime, x0=si,
                        tol=1e-7, maxiter=5)
            except RuntimeError:
                s[i] = np.nan
        return s # np.where(s>=0, s, np.nan) # TODO mask

    def refract(self, y, u0, mu):
        # G. H. Spencer and M. V. R. K. Murty
        # General Ray-Tracing Procedure
        # JOSA, Vol. 52, Issue 6, pp. 672-676 (1962)
        # doi:10.1364/JOSA.52.000672
        if mu == 1:
            return u0
        r = self.shape_func_deriv(y)
        r2 = np.square(r).sum(1)
        muf = abs(mu)
        a = muf*(u0*r).sum(1)/r2
        # solve g**2 + 2*a*g + b=0
        if mu == -1:
            u = u0 - 2*a[:, None]*r # reflection
        else:
            b = (mu**2 - 1)/r2
            g = -a + np.sign(mu)*np.sqrt(a**2 - b)
            u = muf*u0 + g[:, None]*r # refraction
        return u

    def surface_cut(self, axis, points):
        xyz = super(Interface, self).surface_cut(axis, points)
        xyz[:, 2] = -self.shape_func(xyz)
        return xyz


class Spheroid(Interface):
    typ = "S"

    def __init__(self, curvature=0., conic=1., aspherics=None, **kwargs):
        super(Spheroid, self).__init__(**kwargs)
        self.curvature = curvature
        self.conic = conic
        if aspherics is not None:
            aspherics = np.array(aspherics)
        self.aspherics = aspherics
        if self.curvature and np.isfinite(self.radius):
            assert self.radius**2 < 1/(self.conic*self.curvature**2)

    def shape_func(self, xyz):
        x, y, z = xyz.T
        r2 = x**2 + y**2
        c, k = self.curvature, self.conic
        e = c*r2/(1 + np.sqrt(1 - k*c**2*r2))
        if self.aspherics is not None:
            for i, ai in enumerate(self.aspherics):
                e += ai*r2**(i + 2)
        return z - e

    def shape_func_deriv(self, xyz):
        x, y, z = xyz.T
        r2 = x**2 + y**2
        c, k = self.curvature, self.conic
        e = c/np.sqrt(1 - k*c**2*r2)
        if self.aspherics is not None:
            for i, ai in enumerate(self.aspherics):
                e += 2*ai*(i + 2)*r2**(i + 1)
        q = np.ones((e.size, 3))
        q[:, 0] = -x*e
        q[:, 1] = -y*e
        return q

    def intercept(self, y, u):
        if self.aspherics is not None:
            return Interface.intercept(self, y, u) # expensive iterative
        # replace the newton-raphson with the analytic solution
        c = self.curvature
        if c == 0:
            return -y[:, 2]/u[:, 2] # flat
        ky, ku = y, u
        if self.conic != 1:
            ky, ku = ky.copy(), ku.copy()
            ky[:, 2] *= self.conic
            ku[:, 2] *= self.conic
        d = c*(u*ky).sum(1) - u[:, 2]
        e = c*(u*ku).sum(1)
        f = c*(y*ky).sum(1) - 2*y[:, 2]
        s = (-d - np.sign(u[:, 2])*np.sqrt(d**2 - e*f))/e
        return s #np.where(s*np.sign(self.distance)>=0, s, np.nan)

    def paraxial_matrix(self, n0, l):
        # [y', u'] = M * [y, u]
        c = self.curvature
        if self.aspherics is not None:
            c += 2*self.aspherics[0]
        d = self.distance
        md = np.eye(4)
        md[0, 2] = md[1, 3] = d

        theta = self.angles[0] if self.angles is not None else 0.
        costheta = np.cos(theta)
        n = n0
        m = np.eye(4)
        if self.material is not None:
            if self.material.mirror:
                m[2, 0] = 2*c*costheta
                m[3, 1] = 2*c/costheta
                m = -m
            else:
                n = self.refractive_index(l)
                mu = n/n0
                p = np.sqrt(mu**2 - np.sin(theta)**2)
                m[1, 1] = p/(mu*costheta)
                m[2, 0] = c*(costheta - p)/mu
                m[3, 1] = c*(costheta - p)/(costheta*p)
                m[2, 2] = 1./mu
                m[3, 3] = costheta/p
        m = np.dot(m, md)

        if self.angles is not None:
            # rotation around optical axis # FIXME
            # makes simple astigmatic general astigmatic
            phi = self.angles[2]
            cphi, sphi = np.cos(phi), np.sin(phi)
            r1 = np.array([[cphi, -sphi], [sphi, -cphi]])
            r = np.eye(4)
            r[:2, :2] = r[2:, 2:] = r1
            m = np.dot(r, np.dot(m, r.T))

        return n, m
   
    def reverse(self):
        super(Spheroid, self).reverse()
        self.curvature *= -1
        if self.aspherics is not None:
            self.aspherics *= -1

    def rescale(self, scale):
        super(Spheroid, self).rescale(scale)
        self.curvature /= scale
        if self.aspherics is not None:
            self.aspherics /= scale**(2*np.arange(self.aspherics.size) + 1)

    def aberration(self, y, u, n0, n, kmax):
        y, yb = y
        u, ub = u
        c = self.curvature
        f, g = (c*y + u)*n0, (c*yb + ub)*n0
        if self.material is not None and self.material.mirror:
            n = -n # FIXME
        a = np.zeros((2, 2, kmax, kmax, kmax))
        aberration_intrinsic(c, f, g, y, yb, 1/n0, 1/n, a, kmax - 1)
        return a

# aliases as Spheroid has all features
Object = Spheroid
Image = Spheroid
