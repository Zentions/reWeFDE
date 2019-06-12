# -*- coding: utf-8 -*-
import math
from data_utils import logger
from collections import Iterable
from kde_wrapper import KDE
import numpy as np


class WebsiteFingerprintModeler(object):

    def __init__(self, data, sample_size=5000):
        """
        Instantiate a fingerprint modeler.

        Parameters
        ----------
        data : WebsiteData
            Website trace data object
        sample_size : int
            number of samples to use for monte-carlo estimation

        """
        self.data = data
        self.sample_size = sample_size

    def _make_kde(self, features, site=None):
        """
        Produce AKDE for a single feature or single feature for a particular site.

        Parameters
        ----------
        features : list
            Feature(s) of which to model a multi/uni-variate AKDE.
        site : int
            Model features only for the given website number.
            Model all sites if None.

        Returns
        -------

        """
        if not isinstance(features, Iterable):
            features = [features]

        # build X for features
        X = None
        for feature in features:

            # get feature vector
            if site is not None:    # pdf(f|c)
                X_f = self.data.get_site(site, feature)
            else:       # pdf(f)
                X_f = self.data.get_feature(feature)
            X_f = np.reshape(X_f, (X_f.shape[0], 1))

            # extend X w/ feature vector if it has been initialized
            # otherwise, initalize X using the current feature vector
            if X is None:
                X = X_f
            else:
                X = np.hstack((X, X_f))

        # fit KDE on X
        return KDE(X)

    def _sample(self, mkdes, web_priors, sample_size):
        """
        Generate samples from site KDEs.

        Sampling is done on each website KDE.
        The number of samples drawn from each website is determined by prior.
        Selected samples are later used for monte-carlo evaluation.

        Parameters
        ----------
        mkdes : list
            list of site AKDEs from which to sample
        web_priors : list
            list of website priors
        sample_size : int
            number of samples to generate

        Returns
        -------
        list
            List of instance samples.
            The dimension of the samples depends on the number of features used to generate the AKDEs.
        """
        samples = []
        for site_mkdes in mkdes:
            group_samples = []
            for site, mkde in zip(self.data.sites, site_mkdes):

                # n = k * pr(c[i]) -- number of samples per site
                num = int(sample_size * web_priors[site])

                if num > 0:
                    # sample from pdf(f|c[i])
                    x = mkde.sample(num)
                    group_samples.extend(x)
            samples.append(group_samples)

        return samples

    def information_leakage(self, clusters):
        """
        Evaluate the information leakage for feature(s).

        Computes marginal KDEs for features given a sites using AKDEs.
        Conditional entropy is then estimated from the distributions via monte-carlo integration.
        The conditional entropy is then used to compute the leakage for the feature(s)

        Parameters
        ----------
        clusters: list
            A list of lists. Features is a list of clusters.
            Each cluster is a list containing the features in the cluster.
            A singular feature or cluster may be given as the parameter.
            In those instances, the data will be wrapped in additional lists to match the expected form.

        Returns
        -------
        float
            Estimated information leakage for the features/clusters.

        """
        # catch unhandled errors
        try:
            # convert one feature to singular list for comparability
            if not isinstance(clusters, Iterable):
                clusters = [clusters]
            if not isinstance(clusters[0], Iterable):
                clusters = [clusters]

            logger.debug("Measuring leakage for {}".format(clusters))

            # create pdf for sampling and probability calculations
            cluster_mkdes = [[self._make_kde(features, site) for site in self.data.sites] for features in clusters]

            # Shannon Entropy func: -p(x)*log2(p(x))
            h = lambda x: -x * math.log(x, 2)

            # H(C) -- compute website entropy
            website_priors = [1/float(len(self.data.sites)) for _ in self.data.sites]
            H_C = sum([h(prior) for prior in website_priors if prior > 0])

            # performing sampling for monte-carlo evaluation of H(C|f)
            cluster_samples = self._sample(cluster_mkdes, website_priors, self.sample_size)

            # get probabilities of samples from each feature-website density distribution (for each cluster)
            cluster_prob_set = [[mkde.predict(samples) for mkde in site_mkdes]
                                for site_mkdes, samples in zip(cluster_mkdes, cluster_samples)]

            # independence is assumed between clusters
            # get final joint probabilities by multiplying sample probs of clusters together
            prob_set = []
            for i in range(len(cluster_prob_set[0])):
                prob = 1
                for j in range(len(cluster_prob_set)):
                    prob *= cluster_prob_set[j][i]
                prob_set.append(prob)

            # transpose array so that first index represents samples, and the second index represents features
            prob_set = np.array(prob_set).transpose((1, 0))

            # weight by website priors
            prob_temp = [[prob*prior for prob, prior in zip(prob_inst, website_priors)]
                         for prob_inst in prob_set]

            # normalize probabilities?
            prob_indiv = [[prob / sum(prob_inst) for prob in prob_inst]
                          for prob_inst in prob_temp]

            # check for calculation error?
            for prob_inst in prob_indiv:
                if sum(prob_inst) < 0.99:
                    logger.warn('Sum of probs does not equal 1! {}'.format(sum(prob_inst)))

            # compute entropy for instances
            entropies = [sum([h(prob) for prob in prob_inst if prob > 0])
                         for prob_inst in prob_indiv]

            # H(C|f) -- compute conditional entropy via monte-carlo from sample probabilities
            H_CF = sum(entropies)/len(entropies)

            # I(C;f) = H(C) - H(C|f) -- compute information leakage
            leakage = H_C - H_CF

            # debug output
            logger.debug("{l} = {c} - {cf}"
                         .format(l=leakage, c=H_C, cf=H_CF))

            return leakage

        except not KeyboardInterrupt:
            # in cases where there is an unknown error, save leakage as N/A
            # ignore these features when computing combined leakage
            logger.exception("Exception when estimating leakage for {}.".format(clusters))
            return None

    def __call__(self, features):
        return self.information_leakage(features)
