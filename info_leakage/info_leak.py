"""
Main project file which performs info-leak measure
"""
import argparse
import sys
import dill
import os
from pathos.multiprocessing import cpu_count
from pathos.multiprocessing import ProcessPool as Pool

from fingerprint_modeler import WebsiteFingerprintModeler
from mi_analyzer import MutualInformationAnalyzer
from data_utils import load_data, WebsiteData, logger


def individual_measure(fingerprinter, pool=None, checkpoint=None):
    """
    Perform information leakage analysis for each feature one-by-one.
    The resulting leakages can be saved in a plain-text ascii checkpoint file,
     which can be loaded in subsequent runs to avoid re-processing features.
    :param fingerprinter: WebsiteFingeprintModeler analysis engine
    :param pool: pathos multiprocess pool
    :return: list of leakages where the index of each leakage maps to the feature number
    """
    leakage_indiv = []

    # open a checkpoint file
    if checkpoint:
        tmp_file = open(checkpoint, 'a+')
        past_leaks = [float(line) for line in tmp_file]
        lines = len(past_leaks)
        leakage_indiv = past_leaks

    # if a pool has been provided, perform computation in parallel
    # otherwise do serial computation
    if checkpoint:
        features = fingerprinter.data.features[lines:]
    else:
        features = fingerprinter.data.features
    if pool is None:
        proc_results = map(fingerprinter, features)
    else:
        proc_results = pool.imap(fingerprinter, features)
        pool.close()
    size = len(fingerprinter.data.features)  # number of features

    logger.info("Begin individual leakage measurements.")
    # measure information leakage
    # log current progress at twenty intervals
    for leakage in proc_results:
        if len(leakage_indiv) % int(size*0.05) == 0:
            logger.info("Progress: {}/{}".format(len(leakage_indiv), size))
        leakage_indiv.append(leakage)
        if checkpoint:
            tmp_file.write('{}\n'.format(str(leakage)))
            tmp_file.flush()
    if pool is not None:
        pool.join()
        pool.restart()
    if checkpoint:
        tmp_file.close()
    return leakage_indiv


def parse_args():
    """
    Parse command line arguments
    Accepted arguments:
      (f)eatures   -- directory which contains feature files
      (i)ndividual -- pickle file where individual leakage is (to be) saved
      (c)ombined   -- pickle file where the combined leakage is to be saved
    """
    parser = argparse.ArgumentParser("TODO: Program description")

    # Required Arguments
    # directory containing feature files
    parser.add_argument("-f", "--features",
                        required=True,
                        type=str,
                        help="Directory which contains files with the .feature extension.")

    # location to save individual measurements,
    # or location from which to load measurements
    parser.add_argument("-i", "--individual",
                        type=str,
                        help="The file used to save or load individual leakage measurements.")

    # location to save combined measurements,
    # or location from which to load measurements
    parser.add_argument("-c", "--combined",
                        type=str,
                        help="The file used to save or load combined leakage measurements.")

    # Optional Arguments
    # number of samples for monte-carlo integration
    parser.add_argument("--n_samples",
                        type=int,
                        default=5000,
                        help="The number of samples to use when performing Monte-Carlo Integration estimation. "
                             "Higher values result in more accurate measurements, but longer runtimes.")
    # redundancy threshold
    parser.add_argument("--nmi_threshold",
                        type=float,
                        default=0.9,
                        help="The theshold value used to identify redundant features. "
                             "A value between 0.0 and 1.0.")
    parser.add_argument("--topn",
                        type=int,
                        default=100,
                        help="The number of top features to save during combined feature analysis")
    # number of processes
    parser.add_argument("--n_procs",
                        type=int,
                        default=0,
                        help="The number of processes to use when performing parallel operations. "
                             "Use '0' to use all available processors.")
    parser.add_argument("--checkpoint",
                        type=str,
                        default='indiv_checkpoint.txt',
                        help="A file which to save checkpoint information for individual leakage processing.")
    return parser.parse_args()


def main(args):
    """
    execute main logic
    """
    # prepare feature dataset
    logger.info("Loading dataset.")
    X, Y = load_data(args.features)
    feature_data = WebsiteData(X, Y)
    logger.info("Loaded {} sites.".format(len(feature_data.sites)))
    logger.info("Loaded {} instances.".format(len(feature_data)))

    # create process pool
    if args.n_procs > 1:
        pool = Pool(args.n_procs)
    elif args.n_procs == 0:
        pool = Pool(cpu_count())
    else:
        pool = None

    # initialize fingerprint modeler
    fingerprinter = WebsiteFingerprintModeler(feature_data,
                                              sample_size=args.n_samples)

    # perform individual information leakage measurements
    leakage_indiv = None
    if args.individual:
        # load previous leakage measurements if possible
        if os.path.exists(args.individual):
            with open(args.individual, "rb") as fi:
                logger.info("Loading saved individual leakage measures.")
                leakage_indiv = dill.load(fi)

        # otherwise do individual measure
        else:
            leakage_indiv = individual_measure(fingerprinter, pool, args.checkpoint)

            # save individual leakage to file
            logger.info("Saving individual leakage to {}.".format(args.individual))
            if os.path.dirname(args.individual):
                os.makedirs(os.path.dirname(args.individual))
            with open(args.individual, "wb") as fi:
                dill.dump(leakage_indiv, fi)

    # perform combined information leakage measurements
    leakage_joint = None
    if args.combined:

        # load joint leakage file
        if os.path.exists(args.combined):
            with open(args.combined, "rb") as fi:
                logger.info("Loading saved joint leakage measures.")
                leakage_joint = dill.load(fi)

        # otherwise do joint leakage estimation
        else:
            # initialize MI analyzer
            analyzer = MutualInformationAnalyzer(feature_data,
                                                 leakage_indiv,
                                                 nmi_threshold=args.nmi_threshold,
                                                 topn=args.topn,
                                                 pool=pool)

            # process into list of non-redundant features
            logger.info("Begin feature pruning.")
            pruned = analyzer.prune()
            with open('top{}.pkl'.format(args.topn), 'w') as fi:
                dill.dump(pruned, fi)

            # cluster non-redundant features
            logger.info("Begin feature clustering.")
            clusters, distance_matrix = analyzer.cluster(pruned)
            with open('clusters.pkl', 'w') as fi:
                dill.dump(clusters, fi)

            logger.info('Identified {} clusters.'.format(len(clusters)))
            logger.info("Begin cluster leakage measurements.")
            leakage_joint = fingerprinter.information_leakage(clusters)

            ## if a pool has been provided, perform computation in parallel
            ## otherwise do serial computation
            #if pool is None:
            #    proc_results = map(fingerprinter, clusters)
            #else:
            #    proc_results = pool.imap(fingerprinter, clusters)
            #    pool.close()

            ## measure information for each cluster
            ## log current progress at twenty intervals
            #leakage_joint = []
            #for leakage in proc_results:
            #    if len(leakage_joint) % int(len(clusters)*0.05) == 0:
            #        logger.info("Progress: {}/{}".format(len(leakage_joint), len(clusters)))
            #    leakage_joint.append(leakage)
            #if pool is not None:
            #    pool.join()
            #    pool.restart()

            # save individual leakage to file
            logger.info("Saving joint leakage to {}.".format(args.combined))
            if os.path.dirname(args.combined):
                os.makedirs(os.path.dirname(args.combined))
            with open(args.combined, "wb") as fi:
                dill.dump(leakage_joint, fi)

    if leakage_indiv is not None:
        logger.info("Joint leakage estimation: {} bits".format(leakage_joint))
    logger.info("Finished execution.")


if __name__ == "__main__":
    try:
        main(parse_args())
    except KeyboardInterrupt:
        sys.exit(-1)


