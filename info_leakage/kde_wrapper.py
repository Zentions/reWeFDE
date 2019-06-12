# -*- coding: utf-8 -*-
import numpy as np
from scipy import stats
import statsmodels.api as sm


class AKDE(object):

    def __init__(self, data, weights=None, bw=None):
        """
        Setup and fit a kernel density estimator to data.

        Parameters
        ----------
        data : ndarray
            Data samples from which to build the KDE.
            The first dimension of the array defines the number of kernels (samples).
            The second dimension defines the number of features per sample.
        weights : ndarray
            Weights for each sample. Array should be of shape (n_samples, 1).
            The summation of all weights should equal to 1.
            If None is used, all samples are weighted equally.
        bw : ndarray
            The bandwidth vector to use. Array should be of shape (n_features, 1)
            If None is used, kernel sizes are automatically determined.

        """
        self._data = data
        self._n_kernels, self._n_features = self._data.shape
        self._weights = weights if weights is not None else np.repeat(1. / self._n_kernels, self._n_kernels)

        if bw is None:
            bw = self._ksizeHall(self._data)
            if np.isnan(bw).any() or np.isinf(bw).any():
                bw = self._ksizeROT(self._data)

        self._bw = bw + (bw == 0.)*0.001    # replace 0.0 with 0.001

        var_vector = ''.join(['c'] * self._n_features)
        self._kde = sm.nonparametric.KDEMultivariate(self._data, var_vector, bw=bw)

    def sample(self, n_samples):
        """
        Draw random samples from the estimator.
        
        Parameters
        ----------
        n_samples : int
            The number of samples to generate.

        Returns
        -------
        ndarray
            A numpy matrix containing samples, of size (n_samples, n_features)
        """
        bw = np.tile(self._bw, (self._n_kernels, 1))
        points = np.zeros((n_samples, self._n_features))
        randnums = np.random.normal(size=(n_samples, self._n_features))

        # weights and thresholds to determine which kernel to sample from
        w = np.cumsum(self._weights)
        w /= np.amax(w) # kernel weights represented as normalized cumsum
        t = np.sort(np.random.uniform(size=(n_samples,))).tolist()
        t.append(1.)   # final threshold value signals sampling is done

        ii = 1
        for i in range(self._n_kernels):
            # if kernel weight is less than threshold, go to next kernel
            # otherwise, continue sampling from current kernel
            while w[i] > t[ii]:
                points[ii, :] = self._data[i, :] + (bw[i, :] * randnums[ii, :])
                ii += 1
        # verify samples are correctly shaped before returning samples
        assert(points.shape[0] == n_samples)
        assert(points.shape[1] == self._data.shape[1])
        return points

    def predict(self, data):
        """
        Predict probability estimate for samples.

        Parameters
        ----------
        data : ndarray
            Data is a numpy array of dimensions (n_samples, n_features).
            The number of features in the data must be the same as the 
            number of features in the data used to fit the estimator.

        Returns
        -------
        ndarray
            A 1D numpy array containing the probabilities for each sample.

        """
        return self._kde.pdf(data)

    def entropy(self, data=None):
        """

        """
        if data is not None:
            probs = self.predict(data)
            if np.any(probs[probs == 0.]):
                return -np.inf
            else:
                return -np.mean(np.log(probs))
        else:
            probs = self.predict(self._data)
            if np.any(self._weights[probs <= 0.]):
                return -np.inf
            else:
                probs[probs == 0.] = 1.
                return -np.dot(np.log(probs), np.transpose(self._weights))


    def _ksizeROT(self, X):
        """
    
        """
        X = np.transpose(X)
        noIQR = 0
        dim = X.shape[0]
        N = X.shape[1]
    
        Rg, Mg = .282095, 1
        Re, Me = .6, .199994
        Rl, Ml = .25, 1.994473
    
        prop = 1.0
    
        sig = np.std(X, axis=1)
        if noIQR:
            h = prop * sig * np.power(N, (-1 / (4 + dim)))
        else:
            iqrSig = .7413 * np.transpose(stats.iqr(np.transpose(X)))
            if np.amax(iqrSig) == 0:
                iqrSig = sig
            h = prop * np.minimum(sig, iqrSig) * np.power(N, (-1 / (4 + dim)))
        return h
    
    def _ksizeHall(self, X):
        """

        """
        X = np.transpose(X)
    
        N1, N2 = X.shape
        sig = np.std(X, axis=1)
        lamS = .7413 * np.transpose(stats.iqr(np.transpose(X)))
        if np.amax(lamS) == 0:
            lamS = sig
        BW = 1.0592 * lamS * np.power(N2, -1 / (4 + N1))
        BW = np.tile(BW, (1, N2))
    
        t = np.transpose(X[:, :, None], (0, 2, 1))
        dX = np.tile(t, (1, N2, 1))
    
        for i in range(N2):
            dX[:, :, i] = np.divide(dX[:, :, i] - X, BW)
        for i in range(N2):
            dX[:, i, i] = 2e22
        dX = np.reshape(dX, (N1, N2*N2))
    
        def h_findI2(n, dXa, alpha):
            t = np.exp(-0.5*np.sum(np.power(dXa,2), axis=0))
            t = (np.power(dXa, 2) - 1) * 1/np.sqrt(2*np.pi) * np.tile(t, (dXa.shape[0], 1))
            s = np.sum(t, axis=1)
            return np.divide(s, n*(n-1)*np.power(alpha, 5))
    
        def h_findI3(n, dXb, beta):
            t = np.exp(-0.5*np.sum(np.power(dXb,2), axis=0))
            t = (np.power(dXb, 3) - (3*dXb)) * 1/np.sqrt(2*np.pi) * np.tile(t, (dXb.shape[0], 1))
            s = np.sum(t, axis=1)
            return -np.divide(s, n*(n-1) * np.power(beta, 7))
    
        I2 = h_findI2(N2, dX, BW[:,1])
        I3 = h_findI3(N2, dX, BW[:,1])
    
        RK, mu2, mu4 = 0.282095, 1.000000, 3.000000
    
        J1 = (RK / mu2**2) * (1./I2)
        J2 = (mu4 * I3) / (20 * mu2) * (1./I2)
        h = np.power((J1/N2).astype(dtype=np.complex), 1.0/5) + (J2 * np.power((J1/N2).astype(dtype=np.complex), 3.0/5))
        h = h.real.astype(dtype=np.float64)
    
        return np.transpose(h)
