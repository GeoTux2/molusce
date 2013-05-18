"""
Multinomial Logistic Regression (MLR)
=====================================

Multiclass-classification with the MLR classifier

The code based on https://gist.github.com/daien/1989208 written by  Adrien Gaidon & Jakob Verbeek

"""


import numpy as np
from scipy.optimize import fmin_bfgs


def mlr_nll_and_gradient(X, Y, W, sigma2, weighted):
    """ Compute the MLR negative log-likelihood and its gradient

    Parameters
    ----------
    X : array-like, shape [n_samples, n_features],
        Training data

    Y : numpy array, shape [n_samples, n_classes],
        Target values

    W : numpy array, shape [n_features, n_classes],
        MLR coefficient estimates

    sigma2: float, optional, default: None,
            Bandwidth of Gaussian prior for MAP estimation
            (penalization parameter)

    weighted: boolean, optional, default: False,
              if False, then assumes Y contains binary labels, and
                    nll = sum_n log sum_c Y[n, c] p(c|data_n)
              if True, then assumes Y contains weights, and
                    nll = sum_n sum_c Y[n, c] log p(c|data_n)

    Returns
    -------
    nll: float,
         the negative log-likelihood of the MLR objective function

    grad: numpy array, shape [n_features, n_classes]
          the gradient of the negative log-likelihood of the MLR objective
    """
    n_samples, n_features = X.shape
    _n, n_classes = Y.shape
    _d, _c = W.shape
    # check dimensions
    assert n_samples == _n, "Shape mismatch between X and Y"
    assert n_features == _d, "Shape mismatch between X and W"
    assert n_classes == _c, "Shape mismatch between Y and W"

    Yhat = np.dot(X, W)
    Yhat -= Yhat.min(axis=1)[:, np.newaxis]
    Yhat = np.exp(-Yhat)
    # l1-normalize
    Yhat /= Yhat.sum(axis=1)[:, np.newaxis]

    if weighted:
        nll = np.sum(np.log((1. + 1e-15) * Yhat) * Y)
        Yhat *= Y.sum(axis=1)[:, np.newaxis]
        Yhat -= Y
    else:
        _Yhat = Yhat * Y
        nll = np.sum(np.log(_Yhat.sum(axis=1)))
        _Yhat /= _Yhat.sum(axis=1)[:, np.newaxis]
        Yhat -= _Yhat
        del _Yhat

    grad = np.dot(X.T, Yhat)

    if sigma2 is not None:
        nll -= np.sum(W * W) / (2. * sigma2)
        nll -= n_features * n_classes * np.log(sigma2) / 2.
        grad -= W / float(sigma2)

    nll /= -float(n_samples)
    grad /= -float(n_samples)

    return nll, grad


class FuncGradComputer(object):
    """ Convenience class to pass func and grad separately to optimize
    """
    def __init__(self, X, Y, ss, weighted):
        self.X = X
        self.Y = Y
        self.ss = ss
        self.weighted = weighted
        # use None value to signal recomputing is necessary
        self.nll_ = None
        self.grad_ = None

    def _compute_func_grad(self, w):
        """ Simultaneously compute objective function and gradient at w
        """
        # reshape  input flattened by scipy
        W = w.reshape((self.X.shape[1], self.Y.shape[1]))
        self.nll_, self.grad_ = mlr_nll_and_gradient(
            self.X, self.Y, W, self.ss, self.weighted)

    def compute_fun(self, w):
        if self.nll_ is None:
            self._compute_func_grad(w)
        nll = self.nll_
        self.nll_ = None  # to mark for recomputing if recalled
        return nll

    def compute_grad(self, w):
        if self.grad_ is None:
            self._compute_func_grad(w)
        grad = self.grad_.ravel()  # need flattened grad
        self.grad_ = None  # to mark for recomputing if recalled
        return grad


class MLR(object):
    """ Multinomial Logistic Regression classifier

    Parameters
    ----------
    sigma2: float, optional, default: None,
            Bandwidth of Gaussian prior for MAP estimation
            (penalization parameter)

    weighted: boolean, optional, default: False,
              if False, then maximize sum_n log sum_c labels(n,c) p(c|data_n)
              if True, then maximize sum_n sum_c labels(n,c) log p(c|data_n)

    Attributes
    ----------
    W_ : numpy array, shape [n_classes, n_features],
         the coefficient estimates

    infos_ : dict,
             various output infos about the optimization
    """
    def __init__(self, ss=None, weighted=False, seed=None):
        assert ss is None or ss > 0, "ss must be None or > 0"
        self.ss = ss
        self.weighted = weighted
        self.seed = seed
        self.W_ = None
        self.nll_ = None
        self.grad_ = None

    def calcSTD(self, X):
        """
        Calculate std errors for the estimated coefficients.

        Attributes
        ----------
        stdErr : numpy array, shape [n_features+1, n_classes],
             the coefficient estimates
        """
        n_samples, n_features = X.shape
        _d, n_classes = self.W_.shape
        # check dimensions
        assert n_features +1 == _d, "Shape mismatch between X and W"

        # predicted probs for 1,2,... k categories
        pr = self.predict_proba(X)#[:,:-1]

        # add column of ones to X
        n_samples, n_features = X.shape
        ones = np.ones( (n_samples,) )
        X = np.column_stack((ones, X))

        N = (n_classes)*(n_features+1)
        # matrix of the second derivates of ML
        sd = np.zeros( (N, N) )
        for i, x in enumerate(X):
            x.shape = (n_features+1, -1)
            x2 = np.dot(x,x.T)

            p = pr[i]
            lp = np.diag(p)

            p.shape = (n_classes, -1)
            p2 = np.dot(p,p.T)

            h = -np.kron((lp-p2), x2)
            assert h.shape == (N ,N)
            sd = sd+h

        self.stdErr = np.diagonal(sd)
        print sd
        self.stdErr.shape = (n_classes, n_features+1)

    def get_intercept(self):
        """Return array of the intercept estimates (numpy array, shape [1, n_classes])
        """
        if self.W_ == None:
            return
        return self.W_[0, :]

    def get_weights(self):
        """Return array of the coefficient estimates (numpy array, shape [n_features, n_classes])
        """
        if self.W_ == None:
            return
        return self.W_[1:, :]

    def fit(self, X, y, maxiter=None):
        """ Fit the model

        Parameters
        ----------
        X : array-like, shape [n_samples, n_features],
            Training data

        y : array-like, shape [n_samples] or [n_samples, n_classes]
            Target values

        Returns
        -------
        self : returns an instance of self.
        """
        n_samples, n_features = X.shape

        # get the target values
        if y.ndim == 1:
            # convert to 1-of-k coding (one-hot)
            assert len(y) == n_samples, "Invalid number of labels"
            self.classes = np.unique(y)
            n_classes = len(self.classes)
            Y = np.zeros((n_samples, n_classes), dtype=np.float64)
            for i, cls in enumerate(self.classes):
                Y[y == cls, i] = 1
        else:
            _n, n_classes = Y.shape
            assert _n == n_samples, "Invalid number of rows in Y"
            self.classes = np.arange(n_classes)
            Y = y

        # add column of ones to X
        ones = np.ones( (n_samples,) )
        X = np.column_stack((ones, X))

        # initialize the weight matrix
        np.random.seed(self.seed)
        w0 = np.random.random(( (n_features+1) * n_classes, ))

        # initialize the functions to compute the cost function and gradient
        fgcomp = FuncGradComputer(X, Y, self.ss, self.weighted)
        fun = fgcomp.compute_fun
        grad = fgcomp.compute_grad

        # minimize with BFGS
        results = fmin_bfgs(fun, w0, fprime=grad, maxiter=maxiter, disp=False, full_output=False)
        self.W_ = results.reshape((n_features+1, n_classes))

        return self


    def predict_proba(self, X):
        """ Probability estimates.

        The returned estimates for all classes, ordered by label.

        Parameters
        ----------
        X : array-like, shape = [n_samples, n_features]
            Vectors to predict

        Returns
        -------
        Yhat : array-like, shape = [n_samples, n_classes]
               Probability of the sample for each class in the model,
               where classes are ordered by arithmetical order.
        """
        # add column of ones to X
        n_samples, n_features = X.shape
        ones = np.ones( (n_samples,) )
        X = np.column_stack((ones, X))

        Yhat = np.dot(X, self.W_)
        Yhat -= Yhat.min(axis=1)[:, np.newaxis]
        Yhat = np.exp(-Yhat)
        # l1-normalize
        Yhat /= Yhat.sum(axis=1)[:, np.newaxis]
        return Yhat


    def predict(self, X):
        """ Predict most likely label

        The returned estimates for all classes, ordered by label.

        Parameters
        ----------
        X : array-like, shape = [n_samples, n_features]
            Vectors to predict

        Returns
        -------
        yhat : array-like, shape = [n_samples]
               The most likely label for each sample.
        """
        Yhat = self.predict_proba(X)
        yhat = self.classes[np.argmax(Yhat, axis=1).squeeze()]
        return yhat
