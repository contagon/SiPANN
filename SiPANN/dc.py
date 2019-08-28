import numpy as np
from abc import ABC, abstractmethod 
import scipy.integrate as integrate
import scipy.special as special
import pkg_resources
import joblib
import gdspy

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression


'''
Similarly to before, we initialize all ANN's and regressions as global objects to speed things up. 
'''
cross_file = pkg_resources.resource_filename('SiPANN','LR/DC_coeffs.joblib')
DC_coeffs  = joblib.load(cross_file)

cross_file = pkg_resources.resource_filename('SiPANN','LR/R_bent_wide.joblib')
R_bent     = joblib.load(cross_file)

C          = 299792458
"""
Helper Functions used throughout classes
"""
"""Return neff for a given wg profile"""
def get_neff(wavelength, width, thickness, sw_angle=90):
    #clean everything
    wavelength, width, thickness, sw_angle = clean_inputs((wavelength, width, thickness, sw_angle))
    #get coefficients
    _, _, _, _, neff = get_coeffs(wavelength, width, thickness, sw_angle)
    
    return neff   
    
"""Returns all of the coefficients"""
def get_coeffs(wavelength, width, thickness, sw_angle):
    #get coeffs from LR model - needs numbers in nm
    inputs = np.column_stack((wavelength, width, thickness, sw_angle))
    coeffs = DC_coeffs.predict(inputs)
    ae = coeffs[:,0]
    ao = coeffs[:,1]
    ge = coeffs[:,2]
    go = coeffs[:,3]
    neff = coeffs[:,4]
    
    return (ae, ao, ge, go, neff)
    
"""Plugs coeffs into actual closed form function"""
def get_closed_ans(ae, ao, ge, go, neff, wavelength, gap, B, xe, xo, offset, trig, z_dist):
    even_part = ae*np.exp(-ge*gap)*B(xe)/ge
    odd_part  = ao*np.exp(-go*gap)*B(xo)/go
    phase_part= 2*z_dist*neff
        
    mag =  trig( (even_part+odd_part)*np.pi / wavelength )
    phase = (even_part+odd_part-phase_part)*np.pi/wavelength + offset

    return mag*np.exp(-1j*phase)

"""Makes all inputs as the same shape to allow passing arrays through"""
def clean_inputs(inputs):
    inputs = list(inputs)
    #make all scalars into numpy arrays
    for i in range(len(inputs)):
        if np.isscalar(inputs[i]):
            inputs[i] = np.array([inputs[i]])
    
    #take largest size of numpy arrays, or set value (if it's not 0)
    n = max([len(i) for i in inputs])
    
    #if it's smaller than largest, make array full of same value
    for i in range(len(inputs)):
        if len(inputs[i]) != n:
            if len(inputs[i]) != 1:
                raise ValueError("Mismatched Input Array Size")
            inputs[i] = np.full((n), inputs[i][0])
         
    return inputs


"""
Abstract Class that all directional couplers inherit from. Each DC will inherit from it and have initial arguments (in this order): 

width, thickness, sw_angle=90

in that order. Also, each will have additional arguments as follows (in this order):

RR:                  radius, gap
Racetrack Resonator: radius, gap, length
Straight:            gap, length

"""
class DC(ABC):
    """Base Class for DC. All other DC classes should be based on this one, including same functions (so 
        documentation should be the same). Ports are numbered as:
                2---\      /---4
                     ------
                     ------
                1---/      \---3     
    """
    def __init__(self, width, thickness, sw_angle=90):
        self.width      = width
        self.thickness  = thickness
        self.sw_angle   = sw_angle
        
    def clean_args(self, wavelength):
        """Makes sure all attributes are the same size"""
        if wavelength is None:
            return clean_inputs((self.width, self.thickness, self.sw_angle))
        else:
            return clean_inputs((wavelength, self.width, self.thickness, self.sw_angle))
        
    def update(self, **kwargs):
        """Takes in any parameter defined by __init__ and changes it."""
        #apply them
        self.width      = kwargs.get('width', self.width)
        self.thickness  = kwargs.get('thickness', self.thickness)
        self.sw_angle   = kwargs.get('sw_angle', self.sw_angle)
    
    def sparams(self, wavelength):
        """Returns sparams
        Args:
            wavelength(float/np.ndarray): wavelengths to get sparams at
        Returns:
            freq     (np.ndarray): frequency for s_matrix in Hz, size n (number of wavelength points)
            s_matrix (np.ndarray): size (4,4,n) complex matrix of scattering parameters
        """
        #get number of points to evaluate at
        if np.isscalar(wavelength):
            n = 1
        else:
            n = len(wavelength)

        #check to make sure the geometry isn't an array    
        if len(self.clean_args(None)[0]) != 1:
            raise ValueError("You have changing geometries, getting sparams doesn't make sense")
        s_matrix = np.zeros((4,4,n), dtype='complex')
        
        #calculate upper half of matrix (diagonal is 0)
        for i in range(2,5):
            for j in range(i,5):
                s_matrix[i-1,j-1] = self.predict((i,j), wavelength)
                s_matrix[i-1,j-1] = self.predict((i,j), wavelength)
            
        #apply symmetry (note diagonal is 0, no need to subtract it)
        s_matrix += np.transpose(s_matrix, (1,0,2))
        freq = C/(wavelength*10**-9)
        
        #flip them so frequency is increasing
        if n != 1:
            freq = freq[::-1]
            s_matrix = s_matrix[:,:,::-1]
            
        return (freq, s_matrix)
        
    @abstractmethod
    def predict(self, ports, wavelength):
        """Predicts the output when light is put in the bottom left port (see diagram above)

        Args:
            ports               (2-tuple): Specifies the port coming in and coming out
            wavelength (float/np.ndarray): wavelength(s) to predict at

        Returns:
            k/t (complex np.ndarray): returns the value of the light coming through"""
        pass
        
    @abstractmethod
    def gds(self, filename, extra=0):
        """Writes the geometry to the gds file"""
        pass
    
    
"""
All the Different types of DC's with close form solutions. These will be faster than defining it manually in the function form.
"""
class RR(DC):
    def __init__(self, width, thickness, radius, gap, sw_angle=90):
        super().__init__(width, thickness, sw_angle)
        self.radius = radius
        self.gap    = gap
        
    def update(self, **kwargs):
        super().update(**kwargs)
        self.radius = kwargs.get('radius', self.radius)
        self.gap    = kwargs.get('gap', self.gap)
        
    def clean_args(self, wavelength):
        if wavelength is None:
            return clean_inputs((self.width, self.thickness, self.sw_angle, self.radius, self.gap))
        else:
            return clean_inputs((wavelength, self.width, self.thickness, self.sw_angle, self.radius, self.gap))        
    def predict(self, ports, wavelength):
        wavelength, width, thickness, sw_angle, radius, gap = self.clean_args(wavelength)
        ae, ao, ge, go, neff = get_coeffs(wavelength, width, thickness, sw_angle)
        
        #determine if cross or through port
        if ports[1] - ports[0] == 2:
            trig   = np.cos
            offset = 0
        else:
            trig   = np.sin
            offset = np.pi/2
            
        #determine z distance
        if 1 in ports and 3 in ports:
            z_dist = 2 * (radius + width/2)
        elif 1 in ports and 4 in ports:
            z_dist = np.pi*radius/2 + radius+width/2
        elif 2 in ports and 4 in ports:
            z_dist = np.pi * radius
        elif 2 in ports and 3 in ports:
            z_dist = np.pi*radius/2 + radius+width/2
        #if it's coming to itself, or to adjacent port
        else:
            return np.zeros(len(wavelength))    
            
        #calculate everything
        B = lambda x: np.pi*x*np.exp(-x)*(special.iv(1,x) + special.modstruve(-1,x))
        xe = ge*(radius + width/2)
        xo = go*(radius + width/2)
        return get_closed_ans(ae, ao, ge, go, neff, wavelength, gap, B, xe, xo, offset, trig, z_dist)
    
    def gds(filename, self, extra=0, units='nm'):
        raise NotImplemented('TODO: Write to GDS file')

        
class Racetrack(DC):
    def __init__(self, width, thickness, radius, gap, length,  sw_angle=90):
        super().__init__(width, thickness, sw_angle)
        self.radius = radius
        self.gap    = gap
        self.length = length
        
    def update(self, **kwargs):
        super().update(**kwargs)
        self.radius = kwargs.get('radius', self.radius)
        self.gap    = kwargs.get('gap', self.gap)
        self.length = kwargs.get('length', self.length)
        
    def clean_args(self, wavelength):
        if wavelength is None:
            return clean_inputs((self.width, self.thickness, self.sw_angle, self.radius, self.gap, self.length))
        else:
            return clean_inputs((wavelength, self.width, self.thickness, self.sw_angle, self.radius, self.gap, self.length))   
        
    def predict(self, ports, wavelength):
        wavelength, width, thickness, sw_angle, radius, gap, length = self.clean_args(wavelength)
        ae, ao, ge, go, neff = get_coeffs(wavelength, width, thickness, sw_angle)
        
        #determine if cross or through port
        if ports[1] - ports[0] == 2:
            trig   = np.cos
            offset = 0
        else:
            trig   = np.sin
            offset = np.pi/2
            
        #determine z distance
        if 1 in ports and 3 in ports:
            z_dist = 2 * (radius + width/2) + length
        elif 1 in ports and 4 in ports:
            z_dist = np.pi*radius/2 + radius+width/2
        elif 2 in ports and 4 in ports:
            z_dist = np.pi * radius + length
        elif 2 in ports and 3 in ports:
            z_dist = np.pi*radius/2 + radius+width/2 + length
        #if it's coming to itself, or to adjacent port
        else:
            return np.zeros(len(wavelength))    
            
        #calculate everything
        B = lambda x: length*x/(radius+width/2) + np.pi*x*np.exp(-x)*(special.iv(1,x) + special.modstruve(-1,x))
        xe = ge*(radius + width/2)
        xo = go*(radius + width/2)
        return get_closed_ans(ae, ao, ge, go, neff, wavelength, gap, B, xe, xo, offset, trig, z_dist)
    
    def gds(filename, self, extra=0, units='nm'):
        raise NotImplemented('TODO: Write to GDS file')
      
    
class Straight(DC):
    def __init__(self, width, thickness, gap, length,  sw_angle=90):
        super().__init__(width, thickness, sw_angle)
        self.gap    = gap
        self.length = length
        
    def update(self, **kwargs):
        super().update(**kwargs)
        self.gap    = kwargs.get('gap', self.gap)
        self.length = kwargs.get('length', self.length)
        
    def clean_args(self, wavelength):
        if wavelength is None:
            return clean_inputs((self.width, self.thickness, self.sw_angle, self.gap, self.length))
        else:
            return clean_inputs((wavelength, self.width, self.thickness, self.sw_angle, self.gap, self.length))   
        
    def predict(self, ports, wavelength):
        wavelength, width, thickness, sw_angle, gap, length = self.clean_args(wavelength)
        ae, ao, ge, go, neff = get_coeffs(wavelength, width, thickness, sw_angle)
        
        #determine if cross or through port
        if ports[1] - ports[0] == 2:
            trig   = np.cos
            offset = 0
        else:
            trig   = np.sin
            offset = np.pi/2
            
        #determine z distance
        if 1 in ports and 3 in ports:
            z_dist = length
        elif 1 in ports and 4 in ports:
            z_dist = length
        elif 2 in ports and 4 in ports:
            z_dist = length
        elif 2 in ports and 3 in ports:
            z_dist = length
        #if it's coming to itself, or to adjacent port
        else:
            return np.zeros(len(wavelength))    
            
        #calculate everything
        B = lambda x: x
        xe = ge*length
        xo = go*length
        return get_closed_ans(ae, ao, ge, go, neff, wavelength, gap, B, xe, xo, offset, trig, z_dist)
    
    def gds(filename, self, extra=0, units='nm'):
        raise NotImplemented('TODO: Write to GDS file')