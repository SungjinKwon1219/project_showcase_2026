import numpy as np

#Takes all estimated beta as input to create observed distribution
beta = [0.012, 0.010, 0.015, 0.020]

data_Observed = np.array(beta)
sigma_Oserved = data_Observed.std()
weight = 0.1

#Prior distribution weight determined by sd of prior
mu0, tau0 = 0.015, 0.0025

#comparing two
def normal_posterior(data, sigma, mu0, tau0):
    n = len(data)
    xbar = data.mean()
    var_post = 1 / (1/tau0**2 + n/sigma**2)
    mu_post = var_post * (mu0/tau0**2 + (n * xbar)/sigma**2)
    return mu_post

#Initial result
updated_beta = normal_posterior(data_Observed, sigma_Oserved, mu0, tau0)

#Weighted result
weighted_beta = updated_beta * (1 - weight) + mu0 * weight
