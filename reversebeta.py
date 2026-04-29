#Need estimated_beta user info and drinking session info
import math as math

def BACCalculator(alc_g, weight, r, beta, time):
    return (alc_g / (weight * 1000 * r))*100 - beta * time

#calculating alcohol grams absorbed over time
#adjusted for food intake which slows the rate from an expected 15-30 minutes to over an hour
#can use for calculating peak drunkness
def absorbtion(food, grams_alc, intake_time, time):
    peak_time = 0.25
    if food == "Low":
        peak_time = 0.5
    elif food == "Mid":
        peak_time = 1.25
    elif food == "High":
        peak_time = 1.5
    if time < intake_time:
        return 0.0
    elif time >= (intake_time + peak_time):
        return float(grams_alc)
    else:
        return math.sqrt(grams_alc ** 2 - (((time - intake_time - peak_time) ** 2) * (grams_alc ** 2))/(peak_time ** 2))
    

#times are in hours from start
grams_alc = [14.0, 28.0, 14.0, 21.0, 14.0]
times_drink = [0.0, 0.75, 1.5, 2.5, 3.5]
old_beta_estimate = 0.015
sober_time = 9.5
blackout = False
yak = False
food_intake = "High"
final_drunkness = 0.02

user_weight = 75
user_r = 0.68

#Checking if BAC ever reaches zero durring session requires at least two drinks
#Implies rate of alcohol absorbtion is lower than elimination and body has processed all absorbed alcohol already
#Sets new time zero to the time of next shot and subtracts volume of alcohol absorbed before that
i0 = 0
subtract_factor = 0

if len(times_drink) >= 2:
    for i in range(0, (len(times_drink) - 1)):
        current_alc = 0
        for j in range(i0, i+1):
            current_alc += absorbtion(food_intake, grams_alc[j], times_drink[j], times_drink[i + 1])
        if (times_drink[i+1] - times_drink[i0]) * old_beta_estimate > (current_alc / (user_weight * 1000 * user_r))*100:
            subtract_factor = current_alc
            i0 = i+1

#Calculate off of 0.02% as the functionaly sober range
total_g_alc = sum(grams_alc) - subtract_factor
start_time = times_drink[i0]

beta = -(final_drunkness - (total_g_alc / (user_weight * 1000 * user_r))*100) / (sober_time - start_time)

print(beta)
