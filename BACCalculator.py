#Linear Regression Coefficients Men
m_i = 0.3901319484
m_age = 0.0003273190
m_weight = -0.0009810014
m_height = 0.0011555900
m_low = 0.1173256496
m_mid = 0.0633215674

#Linear Regression Coefficients Women
f_i = 0.3945319640
f_age = 0.0001213782
f_weight = -0.0014620109
f_height = 0.0009572304
f_low = 0.1155135171
f_mid = 0.0605819172

#Linear Regression Coefficients Neutral
n_i = 0.2181713778
n_age = -0.0002123286
n_weight = -0.0011931574
n_height = 0.0021444658
n_low = 0.1388081199
n_mid = 0.0756061038

#takes weight as kg and height as cm
def r_coefficient(gender, age, weight, height, fat):
      if gender == "m":
            r_val = m_i + m_age * age + m_weight * weight + m_height * height
            if fat == "low":
                  r_val += m_low
            elif fat == "mid":
                  r_coefficient += m_mid
      elif gender == "f":
            r_val = f_i + f_age * age + f_weight * weight + f_height * height
            if fat == "low":
                  r_val += f_low
            elif fat == "mid":
                  r_val += f_mid
      else:
            r_val = n_i + n_age * age + n_weight * weight + n_height * height
            if fat == "low":
                  r_val += n_low
            elif fat == "mid":
                  r_val += n_mid
      return r_val

def BACCalculator(alc_g, weight, r, beta, time):
    return (alc_g / (weight * 1000 * r)) - beta * time
