| group | tasks | runs | pass^1 | pass^3 | pass^5 | steps | wall s | agent tok | user tok | fab rate | multi-sql | sql err | 0-row write | confirm | last prompt p50/max | terminations |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| overall | 1062 | 1062 | 29.85 | - | - | 6.3 | 1052 | 5277 | 227 | 52.4% | 9.9% | 4.9% | 4.5% | 57% | 2655.0/25107 | {'user_stop': 1007, 'max_steps': 4, 'length_no_content': 38, 'context_overflow': 13} |
| long | 501 | 501 | 23.55 | - | - | 7.0 | 1206 | 5986 | 244 | 54.1% | 13.0% | 5.8% | 5.0% | 62% | 2606/25107 | {'max_steps': 2, 'user_stop': 472, 'length_no_content': 22, 'context_overflow': 5} |
| short | 561 | 561 | 35.47 | - | - | 5.7 | 914 | 4645 | 212 | 50.8% | 7.1% | 4.1% | 4.1% | 53% | 2742/20881 | {'user_stop': 535, 'length_no_content': 16, 'context_overflow': 8, 'max_steps': 2} |
| bowling | 111 | 111 | 16.22 | - | - | 6.2 | 1412 | 6805 | 225 | 62.2% | 7.2% | 3.6% | 3.6% | 69% | 1826/4252 | {'user_stop': 98, 'max_steps': 1, 'length_no_content': 12} |
| car | 27 | 27 | 44.44 | - | - | 5.3 | 1133 | 4957 | 165 | 51.9% | 0.0% | 7.4% | 7.4% | 46% | 1124/2047 | {'user_stop': 24, 'context_overflow': 2, 'length_no_content': 1} |
| chinook | 44 | 44 | 27.27 | - | - | 6.5 | 849 | 4379 | 196 | 45.5% | 6.8% | 9.1% | 0.0% | 55% | 2172.5/2905 | {'user_stop': 43, 'length_no_content': 1} |
| cookbook | 51 | 51 | 17.65 | - | - | 6.8 | 1108 | 5112 | 225 | 37.3% | 17.6% | 7.8% | 9.8% | 52% | 1336/21938 | {'user_stop': 48, 'length_no_content': 2, 'max_steps': 1} |
| entertainment | 131 | 131 | 32.82 | - | - | 6.6 | 983 | 5018 | 199 | 56.5% | 9.2% | 5.3% | 4.6% | 53% | 2092/4856 | {'user_stop': 125, 'max_steps': 1, 'length_no_content': 5} |
| eu_soccer | 215 | 215 | 40.47 | - | - | 4.8 | 600 | 4547 | 232 | 58.1% | 8.4% | 3.7% | 6.0% | 46% | 4351/20016 | {'user_stop': 205, 'context_overflow': 4, 'length_no_content': 6} |
| human_resources | 40 | 40 | 30.00 | - | - | 5.5 | 767 | 3811 | 186 | 62.5% | 2.5% | 0.0% | 2.5% | 56% | 1099/2218 | {'user_stop': 39, 'context_overflow': 1} |
| ice_hockey | 28 | 28 | 21.43 | - | - | 5.9 | 1038 | 5482 | 214 | 64.3% | 7.1% | 0.0% | 3.6% | 82% | 1437.0/2625 | {'user_stop': 28} |
| law_episode | 53 | 53 | 37.74 | - | - | 5.3 | 788 | 4075 | 186 | 54.7% | 3.8% | 1.9% | 3.8% | 41% | 1390/2216 | {'user_stop': 51, 'length_no_content': 2} |
| music | 21 | 21 | 33.33 | - | - | 8.4 | 1187 | 6441 | 208 | 33.3% | 19.0% | 14.3% | 9.5% | 50% | 2479/4623 | {'user_stop': 20, 'length_no_content': 1} |
| pagila | 105 | 105 | 35.24 | - | - | 8.0 | 1172 | 5551 | 242 | 46.7% | 15.2% | 8.6% | 1.9% | 66% | 3447/8146 | {'user_stop': 105} |
| retail | 205 | 205 | 20.00 | - | - | 7.0 | 1472 | 6099 | 266 | 47.3% | 13.7% | 4.4% | 4.9% | 71% | 2956.5/25107 | {'user_stop': 190, 'context_overflow': 6, 'length_no_content': 8, 'max_steps': 1} |
| retail_world | 31 | 31 | 41.94 | - | - | 7.3 | 861 | 4405 | 266 | 32.3% | 6.5% | 3.2% | 0.0% | 50% | 1481/2610 | {'user_stop': 31} |

Top mismatched tables: [('sales', 104), ('costs', 99), ('Player', 83), ('Bowler_Scores', 64), ('Bowler_Scores_Archive', 51)]
