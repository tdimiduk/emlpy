from __future__ import division

try:
    from holopy.fitting.fit import CostComputer
    from holopy.fitting.errors import ParameterSpecificationError
    from holopy.fitting.model import Model
    from holopy.core.holopy_object import HoloPyObject
    import prior
    from random_subset import make_subset_data

    from emcee import PTSampler, EnsembleSampler
    
    from time import time
    import numpy as np
except ImportError:
    pass

import matplotlib.pyplot as plt
from holopy.core.io.io import get_emily_data

class ProbabilityComputer(HoloPyObject):
    def lnprob(self):
        raise NotImplementedError


class Emcee(HoloPyObject):
    def __init__(self, model, data, nwalkers=50, random_subset=None, threads=None, preprocess=None):
        self.model = model
        if preprocess is None:
            preprocess = lambda x: x
        if data.ndim == 3:
            self.n_frames = data.shape[2]
            self.data = [make_subset_data(preprocess(data[..., i]), random_subset)
                         for i in range(self.n_frames)]
        else:
            self.n_frames = 1
            self.data = make_subset_data(preprocess(data), random_subset)
        self.nwalkers = nwalkers
        self.threads = threads


    def make_guess(self):
        return np.vstack([p.sample(size=(self.nwalkers)) for p in self.model.parameters]).T

    def make_sampler(self):
        return EnsembleSampler(self.nwalkers, len(list(self.model.parameters)), self.model.lnposterior, threads=self.threads, args=[self.data])

    def sample(self, n_samples, p0=None):
        sampler = self.make_sampler()
        if p0 is None:
            p0 = self.make_guess()

        sampler.run_mcmc(p0, n_samples)

        return EmceeResult(sampler, self.model)


class PTemcee(Emcee):
    def __init__(self, model, data, noise_sd, nwalkers=20, ntemps=10, random_subset=None, threads=None):
        super(PTemcee, self).__init__(model=model, data=data, noise_sd=noise_sd, nwalkers=nwalkers, random_subset=random_subset, threads=threads)
        self.ntemps = ntemps

    def make_guess(self):
        return np.dstack([p.sample(size=(self.ntemps, self.nwalkers)) for p in self.parameters])

    def make_sampler(self):
        return PTSampler(self.ntemps, self.nwalkers, self.ndim, self.lnlike, self.lnprior, threads=self.threads)


def subset_tempering(model, data=None, final_len=600, nwalkers=500, min_pixels=10, max_pixels=1000, threads='all', stages=3, T=300, stage_len=30, preprocess=None, ):
    """
    I must down to the seas again, to the lonely sea and the sky, And all I ask
is a tall ship and an Emily to steer her by, And the wheel's kick and the wind's
song and the white sail's shaking, And a grey mist on the sea's face, and a grey
dawn breaking.

I must down to the seas again, for the call of the running tide Is a wild call
and a clear call that may not be denied; And all I ask is a windy day with the
white clouds flying, And the flung spray and the blown spume, and the sea-gulls
crying.

I must down to the seas again, to the vagrant gypsy life, To the gull's way and
the whale's way where the wind's like a whetted knife; And all I ask is a merry
yarn from a laughing Emily-rover And quiet sleep and a sweet dream when the
long trick's over.


    Parameters
    ----------
    final_len: int
        Number of samples to use in final run
    stages: int
        Number subset stages to use
    min_pixels: int
        Number of pixels to use in the first stage
    max_pixels: int
        Number of pixels to use in the final stage
    stage_len: int
        Number of samples to use in preliminary stages
    """
    if T > 280:
        plt.imshow(get_emily_data('posterior.jpg'))
    else:
        plt.imshow(get_emily_data('posterior-low-T.jpg'))

    if threads == 'all':
        import multiprocessing
        threads = multiprocessing.cpu_count()
    if threads != None:
        print("Using {} threads".format(threads))

    return None

    if preprocess is None:
        preprocess = lambda x: x

    if data.ndim > 2:
        n_pixels = preprocess(data[...,0]).size
    else:
        n_pixels = preprocess(data).size
    fractions = np.logspace(np.log10(min_pixels), np.log10(max_pixels), stages+1)/n_pixels

    stage_fractions = fractions[:-1]
    final_fraction = fractions[-1]

    def new_par(par, v, std=None):
        mu = v.value
        # for an assymetric object, be conservative and choose the larger deviation
        if std is None:
            std = max(v.plus, v.minus)
        if hasattr(par, 'lower_bound'):
            return prior.BoundedGaussian(mu, std, getattr(par, 'lower_bound', -np.inf), getattr(par, 'upper_bound', np.inf), name=par.name)
        else:
            return prior.Gaussian(mu, std, name=par.name)

    def sample_string(p):
        lb, ub = "", ""
        if getattr(p, 'lower_bound', -np.inf) != -np.inf:
            lb = ", lb={}".format(p.lower_bound)
        if getattr(p, 'upper_bound', np.inf) != np.inf:
            ub = ", ub={}".format(p.upper_bound)
        return "{p.name}: mu={p.mu:.3g}, sd={p.sd:.3g}{lb}{ub}".format(p=p, lb=lb, ub=ub)


    p0 = None
    for fraction in stage_fractions:
        tstart = time()
        emcee = Emcee(model=model, data=data, nwalkers=nwalkers, random_subset=fraction, threads=threads, preprocess=preprocess)
        result = emcee.sample(stage_len, p0)
        try:
            new_pars = [new_par(*p) for p in zip(model.parameters, result.values())]
        except ParameterSpecificationError:
            print("Could not find walkers within 1 sigma of most probable result. Using std of entire ensemble for next stage")
            new_pars = [new_par(*p) for p in zip(model.parameters, result.values(), result.sampler.flatchain.std(axis=0))]
        # TODO need to do something if we come back sd == 0
        p0 = np.vstack([p.sample(size=nwalkers) for p in new_pars]).T
        tend = time()
        print("--------\nStage at f={} finished in {}s.\nDrawing samples for next stage from:\n{}".format(fraction, tend-tstart, '\n'.join([sample_string(p) for p in new_pars])))

    tstart = time()
    emcee = Emcee(model=model, data=data, nwalkers=nwalkers, random_subset=final_fraction, threads=threads)
    result = emcee.sample(final_len, p0)
    tend = time()
    print("--------\nFinal stage at f={}, took {}s".format(final_fraction, tend-tstart))
    return result


class EmceeResult(HoloPyObject):
    def __init__(self, sampler, model):
        self.sampler = sampler
        self.model = model

    @property
    def _names(self):
        return [p.name for p in self.model.parameters]

    def plot_traces(self, traces=10, burn_in=0):
        import matplotlib.pyplot as plt
        names = self._names
        samples = self.sampler.chain
        pars = len(names)
        rows = (pars+1)//2
        plt.figure(figsize=(9, rows*2.8), linewidth=.1)
        for var in range(pars):
            plt.subplot(rows, 2, var+1)
            plt.plot(samples[:traces, burn_in:, var].T, color='k', linewidth=.3)
            plt.title(names[var])


    def plot_lnprob(self, traces='all', burn_in=0):
        import matplotlib.pyplot as plt
        if traces == 'all':
            traces = slice(None)
        plt.plot(self.sampler.lnprobability[traces, burn_in:].T, color='k', linewidth=.1)
    @property
    def n_steps(self):
        return self.sampler.lnprobability.shape[1]

    @property
    def approx_independent_steps(self):
        return int(self.n_steps/max(self.sampler.acor))

    @property
    def acceptance_fraction(self):
        return self.sampler.acceptance_fraction.mean()

    def data_frame(self, burn_in=0, thin='acor', include_lnprob=True):
        """
        Format the results into a data frame

        Parameters
        ----------
        burn_in : int
            Discard this many samples of burn in
        thin: int or 'acor'
            Thin the data by this factor if an int, or by the parameter
            autocorrelation if thin == 'acor'

        Returns
        -------
        df : DataFrame
            A data frame of samples for each parameter
        """
        import pandas as pd
        if thin == 'acor':
            thin = int(max(self.sampler.acor))
        elif thin is None:
            thin = 1
        chain = self.sampler.chain[:, burn_in::thin, ...]
        names = self._names
        npar = len(names)
        df = pd.DataFrame({n: t for (n, t) in zip(names,
                                                  chain.reshape(-1, npar).T)})
        if include_lnprob:
            df['lnprob'] = self.sampler.lnprobability[:, burn_in::thin].reshape(-1)

        return df

    def pairplots(self, filename=None, include_lnprob=False, burn_in=0, thin='acor', include_vars='all'):

        df = self.data_frame(burn_in=burn_in, thin=thin, include_lnprob=include_lnprob)
        df = df.rename(columns={'center[0]': 'x', 'center[1]': 'y', 'center[2]': 'z' })
        df = df.iloc[:,[list(df.columns).index(v) for v in include_vars]]
        xyz = [x for x in 'x', 'y', 'z' if x in df.columns]
        xyz_enum = [(list(df.columns).index(v), v) for v in xyz]
        import seaborn as sns
        import matplotlib.pyplot as plt

        max_xyz_extent = (df.max() - df.min()).loc[xyz].max()

        def limits(x, y):
            xm = df[x].mean()
            ym = df[y].mean()
            # dividing by two would fill the plot exactly, but it is
            # nicer to have a little space around the outermost point
            e = max_xyz_extent/1.8
            return {'xmin': xm-e, 'xmax': xm+e, 'ymin': ym-e, 'ymax': ym+e}

        def plot():
            g = sns.PairGrid(df)
            g.map_diag(sns.kdeplot)
            g.map_lower(sns.kdeplot, cmap="Blues_d")
            g.map_upper(sns.regplot)
            for i, v in xyz_enum:
                for j, u in xyz_enum:
                    g.axes[j][i].axis(**limits(v, u))
            return g

        if filename is not None:
            isinteractive = plt.isinteractive()
            plt.ioff()
            g = plot()
            g.savefig(filename)
            plt.close(g.fig)
            if isinteractive:
                plt.ion()
        else:
            plot()

    def most_probable_values(self):
        values = self.sampler.chain[np.where(self.sampler.lnprobability ==
                               self.sampler.lnprobability.max())]
        if values.ndim == 2:
            if np.any(values.min(axis=0) != values.max(axis=0)):
                print("warning: multiple values with identical probability, output will be two dimensional")
            else:
                values = values[0]

        return values

    def most_probable_values_dict(self):
        return {n: v for (n, v) in zip(self._names, self.most_probable_values())}


    def values(self):
        d = self.data_frame(thin=None).sort_values('lnprob', ascending=False)
        mp = d.iloc[0,:-1]
        def find_bound(f, i):
            b = d.iloc[0, :-1]
            while (b == mp).any() and i < d.shape[0]:
                b = f(b, d.iloc[i,:-1])
                i+=1
            return b

        i = 0
        while d.lnprob.iloc[i] > d.lnprob.max()-.5 and i < d.shape[0]:
            i+=1

        upper = find_bound(np.maximum, i+1)
        lower = find_bound(np.minimum, i+1)
        return [UncertainValue(mp[p], upper[p]-mp[p], mp[p]-lower[p]) for p in self._names]

    def _repr_html_(self):
        results = "{}".format(", ".join(["{}:{}".format(n, v._repr_latex_()) for n, v in zip(self._names, self.values())]))
        block = """<h4>EmceeResult</h4> {results}
{s.sampler.chain.shape[0]} walkers
{s.n_steps} Steps
~ {s.approx_independent_steps} of which are independent
Acceptance Fraction: {s.acceptance_fraction}
        """.format(s=self, results=results)
        return "<br>".join(block.split('\n'))

class UncertainValue(HoloPyObject):
    """
    Represent an uncertain value

    Parameters
    ----------
    value: float
        The value
    plus: float
        The plus n_sigma uncertainty (or the uncertainty if it is symmetric)
    minus: float or None
        The minus n_sigma uncertainty, or None if the uncertainty is symmetric
    n_sigma: int (or float)
        The number of sigma the uncertainties represent
    """
    def __init__(self, value, plus, minus=None, n_sigma=1):
        self.value = value
        self.plus = plus
        self.minus = minus
        self.n_sigma = n_sigma

    def _repr_latex_(self):
        from IPython.display import Math
        confidence=""
        if self.n_sigma != 1:
            confidence=" (\mathrm{{{}\ sigma}})".format(self.n_sigma)
        display_precision = int(round(np.log10(self.value/(min(self.plus, self.minus))) + .6))
        value_fmt = "{{:.{}g}}".format(max(display_precision, 2))
        value = value_fmt.format(self.value)
        return "${value}^{{+{s.plus:.2g}}}_{{-{s.minus:.2g}}}{confidence}$".format(s=self, confidence=confidence, value=value)
