# range_mean_reversion_v1_btc_eth_15m

Run ID: 20261004T150205Z-7a46d39881da
Strategy: range_mean_reversion_v1 1.0.0
Code hash: cad120a9800c23380cce3bfe08aac5a43084bde453192ebcddf7f4aaa56ecac5
Git commit: c40d5c4d3e345eda56f34474302f86bd1cfc8109
Backend: StudyBackend v1; independent liquidated periods, causal warmup.
Execution: synthetic; funding is not modelled.
No automatic promising/validated designation or future-profit claim.

## Datasets and periods

- BTCUSDT 15m: 0a6032afe6c1e90ece9fe7f09ad8e7630860343b8433ca7f0d720102b54ffa97 (2020-01-01 00:00:00+00:00 .. 2026-09-26 00:00:00+00:00); SHA256 4cd16c93b3cc5c2c5dcf8c47720f7db4121750efb78c7d2fe0d2e4b2c58c9799
- ETHUSDT 15m: 9d4bcb5a0627a70513522de8d967c52697af68220dba52ce626a9915730e35c8 (2020-01-01 00:00:00+00:00 .. 2026-09-26 00:00:00+00:00); SHA256 81a1a2515b321d29fabe33a1aea83896d8208b063d511438cf09f766357e6e0c
Modes: LONG_ONLY, SHORT_ONLY, LONG_SHORT

```json
{
  "train": {
    "start": "2020-02-01T00:00:00Z",
    "end": "2023-01-01T00:00:00Z"
  },
  "validation": {
    "start": "2023-01-01T00:00:00Z",
    "end": "2025-01-01T00:00:00Z"
  },
  "test": {
    "start": "2025-01-01T00:00:00Z",
    "end": "2026-09-26T00:00:00Z"
  },
  "walk_forward": [],
  "cost_stress": {
    "adverse": {
      "trading_fee_pct": 0.1,
      "slippage_pct": 0.06,
      "spread_pct": 0.02
    }
  }
}
```

## Counts and predefined filters

```json
{
  "total_backtests": 120,
  "valid_backtests": 120,
  "failed_backtests": 0,
  "filter_rejected_backtests": 37,
  "survivors": 0,
  "configurations": 6,
  "filters": {
    "minimum_trades": 1,
    "maximum_drawdown_pct": 25.0,
    "minimum_profit_factor": null,
    "minimum_sharpe": null,
    "positive_test": false,
    "cost_stress_survival": false
  }
}
```

## Top configurations

Sorted ONLY by TRAIN/base closed_trades, descending; ties use configuration_id, undefined metrics last. Holdouts are descriptive.

```json
[
  {
    "configuration_id": "9309ed8e0d220add",
    "strategy": "range_mean_reversion_v1",
    "strategy_version": "1.0.0",
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "mode": "LONG_SHORT",
    "parameters": "{\"adx_period\": 14, \"adx_threshold\": 20.0, \"atr_period\": 14, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"lower_zone\": 0.2, \"max_ema_slope_pct\": 0.1, \"minimum_range_atr\": 3.0, \"range_lookback\": 32, \"stop_atr_buffer\": 0.5, \"upper_zone\": 0.8}",
    "filter_status": "FAIL",
    "reason": "test/adverse: max_drawdown_pct:max=25.0; test/base: max_drawdown_pct:max=25.0; train/adverse: max_drawdown_pct:max=25.0; train/base: max_drawdown_pct:max=25.0; validation/adverse: max_drawdown_pct:max=25.0; validation/base: max_drawdown_pct:max=25.0",
    "train_return_pct": -41.675469584618206,
    "train_sharpe": -5.396284481476071,
    "train_max_drawdown_pct": 41.7067054162209,
    "train_profit_factor": 0.4049472101314992,
    "train_closed_trades": 989,
    "train_expectancy": -4.213899856887586,
    "train_long_contribution": -2161.1444215578354,
    "train_short_contribution": -2006.4025369039884,
    "validation_return_pct": -35.90896354160957,
    "validation_sharpe": -7.933270973761698,
    "validation_max_drawdown_pct": 35.91257697888434,
    "validation_profit_factor": 0.3156779735181736,
    "validation_closed_trades": 942,
    "validation_expectancy": -3.8119918833980293,
    "validation_long_contribution": -1813.5296282765012,
    "validation_short_contribution": -1777.3667258844425,
    "test_return_pct": -38.90735807747748,
    "test_sharpe": -9.241351110004285,
    "test_max_drawdown_pct": 39.006294711660495,
    "test_profit_factor": 0.28957207364150617,
    "test_closed_trades": 956,
    "test_expectancy": -4.069807330280086,
    "test_long_contribution": -2036.8438893407092,
    "test_short_contribution": -1853.8919184070533
  },
  {
    "configuration_id": "da10de485833bcd2",
    "strategy": "range_mean_reversion_v1",
    "strategy_version": "1.0.0",
    "symbol": "ETHUSDT",
    "timeframe": "15m",
    "mode": "LONG_SHORT",
    "parameters": "{\"adx_period\": 14, \"adx_threshold\": 20.0, \"atr_period\": 14, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"lower_zone\": 0.2, \"max_ema_slope_pct\": 0.1, \"minimum_range_atr\": 3.0, \"range_lookback\": 32, \"stop_atr_buffer\": 0.5, \"upper_zone\": 0.8}",
    "filter_status": "FAIL",
    "reason": "test/adverse: max_drawdown_pct:max=25.0; test/base: max_drawdown_pct:max=25.0; train/adverse: max_drawdown_pct:max=25.0; train/base: max_drawdown_pct:max=25.0; validation/adverse: max_drawdown_pct:max=25.0; validation/base: max_drawdown_pct:max=25.0",
    "train_return_pct": -29.284669626643122,
    "train_sharpe": -3.543392200431087,
    "train_max_drawdown_pct": 29.54393533683886,
    "train_profit_factor": 0.5539842164262091,
    "train_closed_trades": 778,
    "train_expectancy": -3.7640963530389753,
    "train_long_contribution": -1529.7391382589053,
    "train_short_contribution": -1398.727824405417,
    "validation_return_pct": -37.12384390902047,
    "validation_sharpe": -7.693588656876638,
    "validation_max_drawdown_pct": 37.12384390902047,
    "validation_profit_factor": 0.32769906078699484,
    "validation_closed_trades": 878,
    "validation_expectancy": -4.228228235651552,
    "validation_long_contribution": -2033.364252153319,
    "validation_short_contribution": -1679.0201387487434,
    "test_return_pct": -32.69393861267071,
    "test_sharpe": -6.934672421818757,
    "test_max_drawdown_pct": 32.69393861267072,
    "test_profit_factor": 0.38591186679196493,
    "test_closed_trades": 731,
    "test_expectancy": -4.472495022253178,
    "test_long_contribution": -1492.2630422397403,
    "test_short_contribution": -1777.1308190273328
  },
  {
    "configuration_id": "96c2a5fc9370b70b",
    "strategy": "range_mean_reversion_v1",
    "strategy_version": "1.0.0",
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "mode": "SHORT_ONLY",
    "parameters": "{\"adx_period\": 14, \"adx_threshold\": 20.0, \"atr_period\": 14, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"lower_zone\": 0.2, \"max_ema_slope_pct\": 0.1, \"minimum_range_atr\": 3.0, \"range_lookback\": 32, \"stop_atr_buffer\": 0.5, \"upper_zone\": 0.8}",
    "filter_status": "FAIL",
    "reason": "test/adverse: max_drawdown_pct:max=25.0; train/adverse: max_drawdown_pct:max=25.0; validation/adverse: max_drawdown_pct:max=25.0",
    "train_return_pct": -22.661267766641892,
    "train_sharpe": -3.9154746723575005,
    "train_max_drawdown_pct": 22.691040040493043,
    "train_profit_factor": 0.4258639356218984,
    "train_closed_trades": 507,
    "train_expectancy": -4.4696780604816535,
    "train_long_contribution": 0,
    "train_short_contribution": -2266.126776664198,
    "validation_return_pct": -19.542116855621238,
    "validation_sharpe": -5.903751174186439,
    "validation_max_drawdown_pct": 19.573310340084646,
    "validation_profit_factor": 0.3175923259561292,
    "validation_closed_trades": 478,
    "validation_expectancy": -4.088308965611139,
    "validation_long_contribution": 0,
    "validation_short_contribution": -1954.2116855621243,
    "test_return_pct": -20.7669143928087,
    "test_sharpe": -6.008688715311017,
    "test_max_drawdown_pct": 20.798098343737347,
    "test_profit_factor": 0.30395665384108284,
    "test_closed_trades": 467,
    "test_expectancy": -4.446876743642144,
    "test_long_contribution": 0,
    "test_short_contribution": -2076.6914392808812
  },
  {
    "configuration_id": "949bc1eb82c7793f",
    "strategy": "range_mean_reversion_v1",
    "strategy_version": "1.0.0",
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "mode": "LONG_ONLY",
    "parameters": "{\"adx_period\": 14, \"adx_threshold\": 20.0, \"atr_period\": 14, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"lower_zone\": 0.2, \"max_ema_slope_pct\": 0.1, \"minimum_range_atr\": 3.0, \"range_lookback\": 32, \"stop_atr_buffer\": 0.5, \"upper_zone\": 0.8}",
    "filter_status": "FAIL",
    "reason": "test/adverse: max_drawdown_pct:max=25.0; train/adverse: max_drawdown_pct:max=25.0; train/base: max_drawdown_pct:max=25.0; validation/adverse: max_drawdown_pct:max=25.0",
    "train_return_pct": -24.985763138273022,
    "train_sharpe": -4.185399055865571,
    "train_max_drawdown_pct": 25.025937179173646,
    "train_profit_factor": 0.3817205561992308,
    "train_closed_trades": 487,
    "train_expectancy": -5.130546845641261,
    "train_long_contribution": -2498.576313827294,
    "train_short_contribution": 0,
    "validation_return_pct": -20.758080668744494,
    "validation_sharpe": -5.35685931752098,
    "validation_max_drawdown_pct": 20.82800310006222,
    "validation_profit_factor": 0.3164392724214131,
    "validation_closed_trades": 476,
    "validation_expectancy": -4.360941316963099,
    "validation_long_contribution": -2075.808066874435,
    "validation_short_contribution": 0,
    "test_return_pct": -23.4726095938704,
    "test_sharpe": -6.774215300119896,
    "test_max_drawdown_pct": 23.596544741815194,
    "test_profit_factor": 0.2715583777480964,
    "test_closed_trades": 504,
    "test_expectancy": -4.657263808307673,
    "test_long_contribution": -2347.260959387067,
    "test_short_contribution": 0
  },
  {
    "configuration_id": "2ac98d84377c2c0c",
    "strategy": "range_mean_reversion_v1",
    "strategy_version": "1.0.0",
    "symbol": "ETHUSDT",
    "timeframe": "15m",
    "mode": "LONG_ONLY",
    "parameters": "{\"adx_period\": 14, \"adx_threshold\": 20.0, \"atr_period\": 14, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"lower_zone\": 0.2, \"max_ema_slope_pct\": 0.1, \"minimum_range_atr\": 3.0, \"range_lookback\": 32, \"stop_atr_buffer\": 0.5, \"upper_zone\": 0.8}",
    "filter_status": "FAIL",
    "reason": "test/adverse: max_drawdown_pct:max=25.0; train/adverse: max_drawdown_pct:max=25.0; validation/adverse: max_drawdown_pct:max=25.0",
    "train_return_pct": -16.709892566919514,
    "train_sharpe": -2.5125171290461252,
    "train_max_drawdown_pct": 17.102301985913744,
    "train_profit_factor": 0.5522423480887227,
    "train_closed_trades": 404,
    "train_expectancy": -4.136112021514688,
    "train_long_contribution": -1670.9892566919336,
    "train_short_contribution": 0,
    "validation_return_pct": -22.74205793158638,
    "validation_sharpe": -5.6831667950940945,
    "validation_max_drawdown_pct": 22.756522445667777,
    "validation_profit_factor": 0.30730050395337805,
    "validation_closed_trades": 467,
    "validation_expectancy": -4.8698196855645435,
    "validation_long_contribution": -2274.205793158642,
    "validation_short_contribution": 0,
    "test_return_pct": -16.54147528737576,
    "test_sharpe": -4.255234148945117,
    "test_max_drawdown_pct": 16.638531941362288,
    "test_profit_factor": 0.44872332810371357,
    "test_closed_trades": 378,
    "test_expectancy": -4.37605166332687,
    "test_long_contribution": -1654.147528737557,
    "test_short_contribution": 0
  },
  {
    "configuration_id": "ae8d62d63ad07c85",
    "strategy": "range_mean_reversion_v1",
    "strategy_version": "1.0.0",
    "symbol": "ETHUSDT",
    "timeframe": "15m",
    "mode": "SHORT_ONLY",
    "parameters": "{\"adx_period\": 14, \"adx_threshold\": 20.0, \"atr_period\": 14, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"lower_zone\": 0.2, \"max_ema_slope_pct\": 0.1, \"minimum_range_atr\": 3.0, \"range_lookback\": 32, \"stop_atr_buffer\": 0.5, \"upper_zone\": 0.8}",
    "filter_status": "FAIL",
    "reason": "test/adverse: max_drawdown_pct:max=25.0; train/adverse: max_drawdown_pct:max=25.0; validation/adverse: max_drawdown_pct:max=25.0",
    "train_return_pct": -15.372106714367927,
    "train_sharpe": -2.657998889605465,
    "train_max_drawdown_pct": 15.372106714367927,
    "train_profit_factor": 0.5488953470608628,
    "train_closed_trades": 378,
    "train_expectancy": -4.066694897980984,
    "train_long_contribution": 0,
    "train_short_contribution": -1537.210671436812,
    "validation_return_pct": -18.875482974574464,
    "validation_sharpe": -4.881509170483623,
    "validation_max_drawdown_pct": 18.87548297457446,
    "validation_profit_factor": 0.35355865134146053,
    "validation_closed_trades": 419,
    "validation_expectancy": -4.504888538084674,
    "validation_long_contribution": 0,
    "validation_short_contribution": -1887.5482974574784,
    "test_return_pct": -19.662602464965907,
    "test_sharpe": -5.319211737296516,
    "test_max_drawdown_pct": 19.895080546075448,
    "test_profit_factor": 0.33041035022976084,
    "test_closed_trades": 369,
    "test_expectancy": -5.328618554191351,
    "test_long_contribution": 0,
    "test_short_contribution": -1966.2602464966087
  }
]
```

## Walk-forward and cost stress

Walk-forward selects each fold on TRAIN/base; only selected fold TEST rows are OOS results. Medians below are descriptive, not a compounded portfolio.

Median metrics across configurations (including TRAIN/validation/final TEST):

```csv
period,scenario,return_pct,cagr_pct,sharpe,sortino,max_drawdown_pct,profit_factor,win_rate_pct,expectancy,closed_trades,average_close_exposure_pct,fees_paid,slippage_cost_closed_trades,funding_pnl,long_contribution,short_contribution

diagnostic_2020,adverse,-12.639972027135688,-13.690008919820318,-5.172061147922612,-5.318598785282242,12.66677370023529,0.2636318540314953,25.1375786163522,-7.957921925879704,143.0,0.5764398068181336,672.4327206647465,403.45958163696037,,-735.4148863182588,-824.7412657185371

diagnostic_2020,base,-6.306825936862825,-6.851734139339288,-2.956915152215651,-3.4488309953759915,7.101543618818199,0.5031971009873261,30.621069182389938,-4.030936485587738,143.0,0.5765841500681526,346.50824384816326,207.90493288619626,,-268.7780791112206,-417.75020323474826

diagnostic_2021,adverse,-15.438632356581472,-15.438632356581472,-5.2375128331929535,-5.260139438815168,15.702978690316318,0.26528841910195045,22.35605170387779,-9.486268903021731,151.0,0.4392479657854959,693.0476518589502,415.8284375287593,,-1347.868732641526,-896.7952116784062

diagnostic_2021,base,-9.903907089659185,-9.903907089659185,-3.690201571254561,-3.9635754766626095,10.445780315192234,0.43105452565110697,24.570921286249753,-5.976366750057332,151.0,0.4395280640466751,357.6681490173626,214.60084990888006,,-856.1952734210756,-479.2325240161706

diagnostic_2022,adverse,-16.487762235624043,-16.487762235624043,-6.181093118519273,-6.128320352185554,16.609879056212957,0.30504524095262187,24.173512322179924,-7.837564201789828,203.0,0.679678311459916,925.790678688904,555.4743757418577,,-1148.4267241022071,-1277.6135721423148

diagnostic_2022,base,-8.964877704188158,-8.964877704188158,-3.7261639060874376,-4.1901029274705515,9.349915490482642,0.534822889221586,28.571428571428573,-4.199695798011167,203.0,0.6798621637174154,483.01240598453944,289.8074356772213,,-606.8724094534579,-693.2008038000959

diagnostic_2023,adverse,-20.72537468195116,-20.72537468195116,-8.23737174624144,-7.617534648061328,20.78061503315533,0.09675300207416693,15.362903225806452,-7.924945059173263,252.0,0.8626152625546526,1122.3886306486597,673.4331093089077,,-1799.6400857786662,-1768.3410070014188

diagnostic_2023,base,-11.79644707572275,-11.79644707572275,-6.633453139862569,-6.446542084991448,11.875801675012948,0.2699465832252027,25.57639539552938,-4.391658359489838,252.5,0.8645910997868932,592.3788204554342,355.4272741501834,,-1057.2889073167419,-965.9914262676717

diagnostic_2024,adverse,-19.728152997556904,-19.679943037835436,-6.84502935263801,-6.559962092203265,19.7281529975569,0.17818174030763131,22.41982606332382,-8.31676294064582,228.0,0.8211579724879552,1031.2716182596928,618.7629362853236,,-1751.4967704883684,-1532.5488398444127

diagnostic_2024,base,-11.616180682999726,-11.586361135136592,-5.092912511645734,-5.222254242029783,11.626315394542488,0.3617142024359127,26.49958488999585,-4.973060772606198,228.0,0.8211069886765727,540.6859453537976,324.41155807266216,,-1061.5317630417899,-877.7606968113046

diagnostic_2025,adverse,-24.97932924226648,-24.97932924226648,-8.579702383536711,-7.888480236193338,24.989887175036152,0.15712085016280183,19.68570018101037,-8.415166424202347,303.5,0.9748884268733959,1314.8174679566482,788.8903704217789,,-1786.061770677301,-1849.6989710499229

diagnostic_2025,base,-14.66646204641913,-14.66646204641913,-6.650495622662372,-6.490668726642456,14.70293517028895,0.3299922552484156,23.588119137732434,-5.185047924124191,303.5,0.9751400839505292,699.7060245952575,419.8235856568248,,-1089.5359338610892,-1176.4693398282693

diagnostic_2026,adverse,-15.523852556272317,-20.526291732393744,-8.038572248492535,-7.476466599577005,15.623238262942419,0.15245617098798442,18.670117586912063,-8.16595500969627,182.0,0.8200819641743287,835.7634666910219,501.45802474789394,,-1188.135947952384,-1374.3694636836094

diagnostic_2026,base,-8.809581622793939,-11.802882243872759,-6.057501321166921,-6.011037140010105,8.936761337157423,0.33324431037887425,25.36738479098302,-4.6752670435862225,182.0,0.8232558601718324,434.16383549498346,260.49828703255287,,-597.6744153954369,-814.9485419708625

test,adverse,-36.61664240451607,-23.1255375640704,-8.294769750343525,-7.666728472710001,36.6659675179902,0.1449412843918198,18.69947714466438,-7.540583262488576,485.5,0.8501016586849339,1941.2715911158398,1164.7628028383647,,-2650.320579610656,-2763.0195194772286

test,base,-22.11976199333955,-13.427716402698442,-6.391452007715456,-6.274500808118194,22.197321542776272,0.31718350203542184,24.293623021883324,-4.459685882947661,485.5,0.8503358993424397,1069.9279595615299,641.9567344615527,,-1573.2052854886488,-1815.511368717193

train,adverse,-38.31898840434586,-15.262729335964998,-5.7129161585629245,-5.680791282230463,38.31898840434586,0.2771052615761845,23.744556408303552,-7.3864122545214315,497.0,0.5539075045856847,1961.867514490486,1177.1203000700818,,-2772.4701842384484,-2574.5064578427637

train,base,-23.823515452457457,-8.906807057986082,-3.729433436394294,-4.0757018018147635,23.858488609833344,0.4873796413413806,27.88945597337913,-4.175005939201137,497.0,0.5540555186465175,1082.7949232203537,649.6768970641868,,-1600.3641974754196,-1467.9692479211144

validation,adverse,-35.90120738835755,-19.915182578024485,-7.497268089182235,-7.060619366029358,35.90120738835755,0.12974339602244395,18.256733911867464,-7.295854494700061,476.0,0.7645210886104571,1937.088624177658,1162.253099047112,,-2923.4942060629783,-2758.6865190777016

validation,base,-21.750069300165435,-11.527945580206339,-5.793458984640267,-5.793870815079023,21.792262772864998,0.31701579918877115,25.973402979505902,-4.2945847763073255,477.0,0.7647393653753658,1067.8689584233355,640.7213540925707,,-1923.4469402149102,-1728.1934323165929
```

## Failure reasons

```json
{
  "max_drawdown_pct:max=25.0": 37
}
```

## Parameter patterns among filter survivors

```json
{
  "adx_period": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "adx_threshold": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "ema_period": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "ema_slope_lookback": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "max_ema_slope_pct": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "range_lookback": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "lower_zone": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "upper_zone": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "atr_period": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "minimum_range_atr": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  },
  "stop_atr_buffer": {
    "most_common_20": {},
    "distinct_values": 0,
    "other_configurations": 0
  }
}
```

## Files generated

- experiment_snapshot.yaml: original YAML; relative references resolved in resolved.json
- resolved.json: frozen strategy, defaults, parameters and dataset manifests
- environment.json / provenance.json / plan.json: code/environment and experiment
- ledger.sqlite: individual backtest lifecycle and result hashes
- metrics.csv: all periods, costs, metrics and PASS/FAIL reasons
- leaderboard.csv: configurations ranked on TRAIN/base with holdout columns
- summary.json / summary.md / ai_summary.md: compact research summaries
- run.json / outcome.json: immutable start and terminal records
- <backtest_id>/result.json and equity.parquet: trades, rejections, metrics, equity

Historical results do not establish future profitability.
