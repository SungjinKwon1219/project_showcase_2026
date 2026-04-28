import numpy as np

#Takes all estimated beta as input
#beta = [0.012, 0.010, 0.015, 0.020]

data_Observed = np.array(beta)
sigma_Oserved = data_Observed.std()

# Prior
mu0, tau0 = 0.015, 0.0025

def normal_posterior(data, sigma, mu0, tau0):
    n = len(data)
    xbar = data.mean()
    var_post = 1 / (1/tau0**2 + n/sigma**2)
    mu_post = var_post * (mu0/tau0**2 + (n * xbar)/sigma**2)
    return mu_post

updated_beta = normal_posterior(data_Observed, sigma_Oserved, mu0, tau0)
