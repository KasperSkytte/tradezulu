# Changelog

## [1.22.0](https://github.com/KasperSkytte/tradezulu/compare/v1.21.0...v1.22.0) (2026-08-05)


### Features

* **charts:** set the history window in days, and how much opens on screen ([a9d60ac](https://github.com/KasperSkytte/tradezulu/commit/a9d60ac0139c468ced25ff9f5dce1afd7a0fed13))

## [1.21.0](https://github.com/KasperSkytte/tradezulu/compare/v1.20.1...v1.21.0) (2026-08-05)


### Features

* **chart:** a Studio tab that draws the position on the candles ([0c9eba4](https://github.com/KasperSkytte/tradezulu/commit/0c9eba40d4c44c20e4f20d35398ab25d6d8f2960))
* **chart:** read a trade in your own timezone, optionally ([c98a59d](https://github.com/KasperSkytte/tradezulu/commit/c98a59dc121b0c88999bb75dac24dcb8be33f0d4))
* **copier:** show and correct the symbols a slave was matched to ([f5a3239](https://github.com/KasperSkytte/tradezulu/commit/f5a323909b6d830c221f1a03697de7cb99dafdf0))
* **settings:** the clock choice applies to every time in the journal ([4a84db7](https://github.com/KasperSkytte/tradezulu/commit/4a84db7ecedba517554fdd521242ad5a8ada6cdc))


### Bug fixes

* **accounts:** the broker's clock offset reaches the browser ([53f58bf](https://github.com/KasperSkytte/tradezulu/commit/53f58bf37f00e8586c5e64aa91abc62c34e092f5))
* **api:** stop a healthy terminal reporting itself as "quiet 2 hours ago" ([00ed805](https://github.com/KasperSkytte/tradezulu/commit/00ed8053830eb64da4c90ced80ba0cc0699a35b5))
* **chart:** put the fills and the candles on one clock ([2df97fd](https://github.com/KasperSkytte/tradezulu/commit/2df97fd5bcc7d4a078225ab2e3aed63e180d6a67))
* **copier:** match the instrument when the master is the decorated one ([9660ffe](https://github.com/KasperSkytte/tradezulu/commit/9660ffe1c1bb281d3deb6adb9434ebbee1ece43f))

## [1.20.1](https://github.com/KasperSkytte/tradezulu/compare/v1.20.0...v1.20.1) (2026-08-04)


### Bug fixes

* **reports:** the hour buckets follow the clock setting too ([f37bef5](https://github.com/KasperSkytte/tradezulu/commit/f37bef5c7cc544f75651ba1d6211e5747771b5e1))

## [1.20.0](https://github.com/KasperSkytte/tradezulu/compare/v1.19.0...v1.20.0) (2026-08-04)


### Features

* **settings:** choose between a 24-hour and a 12-hour clock ([3b61095](https://github.com/KasperSkytte/tradezulu/commit/3b610955387ed3a12c819d16dec0a3fa631d2855))


### Bug fixes

* **reports:** read setups from the tags as well as the field ([0331f5e](https://github.com/KasperSkytte/tradezulu/commit/0331f5e51e9ea330229dc8b3095416c16c30aaf8))

## [1.19.0](https://github.com/KasperSkytte/tradezulu/compare/v1.18.0...v1.19.0) (2026-08-04)


### Features

* **dashboard:** show the balance when amounts are on ([4ff435f](https://github.com/KasperSkytte/tradezulu/commit/4ff435fef663a44879c6d7589bc6b4817b737f1b))


### Bug fixes

* **charts:** widen the TradingView window until the trade is in it ([b4d9de9](https://github.com/KasperSkytte/tradezulu/commit/b4d9de97b4d12eaf3af2eac21f3dfed69ac86d65))
* **stats:** the newest trades had no Net ROI ([a0ba5d1](https://github.com/KasperSkytte/tradezulu/commit/a0ba5d15e8dba4c5d944c80554ca030d33f8407d))


### Refactoring

* **ui:** put accounts back under settings ([17da78b](https://github.com/KasperSkytte/tradezulu/commit/17da78bb74ab1f97f1d321620fae3c61ff8d4a28))

## [1.18.0](https://github.com/KasperSkytte/tradezulu/compare/v1.17.0...v1.18.0) (2026-08-04)


### Features

* **dashboard:** let a figure about one trade open that trade ([91e9958](https://github.com/KasperSkytte/tradezulu/commit/91e99589031214bf785c4221242dbf9cfef3aae1))

## [1.17.0](https://github.com/KasperSkytte/tradezulu/compare/v1.16.0...v1.17.0) (2026-08-04)


### Features

* **news:** make ForexFactory the default, and give it a filter worth using ([36cfd6f](https://github.com/KasperSkytte/tradezulu/commit/36cfd6f8fab456297628c8be07ac2f64cba74fa6))


### Bug fixes

* **settings:** say that a breakeven threshold of 0 switches it off ([e60eda3](https://github.com/KasperSkytte/tradezulu/commit/e60eda3beeabfe9f271207d83f6e502d2b50f034))


### Refactoring

* **news:** controls first, the warning last ([53d0848](https://github.com/KasperSkytte/tradezulu/commit/53d08489382c4a513273111a1de5692ba2ff1638))


### Documentation

* **settings:** explain what "Even losses" actually measures ([4c0bfed](https://github.com/KasperSkytte/tradezulu/commit/4c0bfedcde01cdf3de689625799bc6c7f0f9dc01))

## [1.16.0](https://github.com/KasperSkytte/tradezulu/compare/v1.15.2...v1.16.0) (2026-08-04)


### Features

* **news:** add ForexFactory beside TradingView, and remember the choice ([1bb06bc](https://github.com/KasperSkytte/tradezulu/commit/1bb06bc2bfa62b4e38edfa09fbe0eefbd407a9a2))


### Documentation

* the news calendar has two sources now ([22ca7c2](https://github.com/KasperSkytte/tradezulu/commit/22ca7c2874d1811645f2a689036c37e8bc448228))

## [1.15.2](https://github.com/KasperSkytte/tradezulu/compare/v1.15.1...v1.15.2) (2026-08-04)


### Bug fixes

* **reports:** the axes have to hide money too ([3aac2d6](https://github.com/KasperSkytte/tradezulu/commit/3aac2d6a9c4a4cff227e8066a0c6bea9a6de430f))

## [1.15.1](https://github.com/KasperSkytte/tradezulu/compare/v1.15.0...v1.15.1) (2026-08-03)


### Documentation

* retake the screenshots on an account that is going somewhere ([45f20c9](https://github.com/KasperSkytte/tradezulu/commit/45f20c9a7cb722fce890038cabfc96beb9f88314))

## [1.15.0](https://github.com/KasperSkytte/tradezulu/compare/v1.14.2...v1.15.0) (2026-08-03)


### Features

* **charts:** collect M5 and build every longer timeframe from it ([494fe80](https://github.com/KasperSkytte/tradezulu/commit/494fe808f09413e819ebb41d30000737c921bef0))


### Documentation

* features ([576c2a1](https://github.com/KasperSkytte/tradezulu/commit/576c2a1478cff58b3a5a3d81696a1e3cb88130e1))
* say plainly that attaching an account is GUI automation ([3405a1d](https://github.com/KasperSkytte/tradezulu/commit/3405a1d9c35e7ed1cd4fca19ecf548730ab5911d))
* shorten the feature list, journal first ([6513e7a](https://github.com/KasperSkytte/tradezulu/commit/6513e7ad4ccb84735ab7218332fba79490262693))

## [1.14.2](https://github.com/KasperSkytte/tradezulu/compare/v1.14.1...v1.14.2) (2026-08-03)


### Bug fixes

* **ui:** make archived accounts removable ([8f98efe](https://github.com/KasperSkytte/tradezulu/commit/8f98efeff83c822ad85b0868c81be3318108ec04))


### Refactoring

* **ui:** move manual import to the accounts page ([8412537](https://github.com/KasperSkytte/tradezulu/commit/8412537c58a9f6b144310f53cc16fc3a7414c3d1))

## [1.14.1](https://github.com/KasperSkytte/tradezulu/compare/v1.14.0...v1.14.1) (2026-08-03)


### Bug fixes

* **accounts:** stop creating second masters, and let one be removed ([e56a056](https://github.com/KasperSkytte/tradezulu/commit/e56a056da63a36d84439279b39477f2cc5ad5436))
* **agent:** never run two terminals for one account, and say what is running ([9c3ffa4](https://github.com/KasperSkytte/tradezulu/commit/9c3ffa4930fdc27fbe06cd8ced5060303e764797))
* **ci:** lint every shell script, at a version that does not move ([a2623f9](https://github.com/KasperSkytte/tradezulu/commit/a2623f9afd9f7bfd91d9a41e40ba05a36c71437e))
* **reports:** honour the amounts setting here too ([cf2e3e1](https://github.com/KasperSkytte/tradezulu/commit/cf2e3e1f2d64d00323c7f0b64707dce3bfed41ad))


### Refactoring

* **ui:** put forgetting and terminal status on the account they describe ([5dace4d](https://github.com/KasperSkytte/tradezulu/commit/5dace4d0c0722e0f0b7333813d3bb6da25bbd2a6))

## [1.14.0](https://github.com/KasperSkytte/tradezulu/compare/v1.13.1...v1.14.0) (2026-08-03)


### Features

* **score:** put drawdown back, and let every component be switched off ([735db68](https://github.com/KasperSkytte/tradezulu/commit/735db68ddc9bb6053c7ada9f584daa73c39b9418))


### Bug fixes

* **stats:** work out balances backwards from what the account is worth ([47a1294](https://github.com/KasperSkytte/tradezulu/commit/47a12949bc55f77215d835e0bdedf0ee2611e936))


### Refactoring

* **settings:** name the amounts toggle after what it does ([65c4268](https://github.com/KasperSkytte/tradezulu/commit/65c42684fc0aa982559fbb01c3cf0fa79261f364))

## [1.13.1](https://github.com/KasperSkytte/tradezulu/compare/v1.13.0...v1.13.1) (2026-08-03)


### Bug fixes

* **agent:** recover a terminal that starts but never works ([4a4d264](https://github.com/KasperSkytte/tradezulu/commit/4a4d2643751a05a7bfff66829f371ee3757046c4))
* **agent:** say which accounts still exist, not just which want a terminal ([e5a4d95](https://github.com/KasperSkytte/tradezulu/commit/e5a4d95e851e5887e44452d0aac186626113186c))
* **install:** check for the commands the terminals need, not dpkg's word ([426a14a](https://github.com/KasperSkytte/tradezulu/commit/426a14a9d8106732c0ee9d9d15962be6dd7c3ccd))
* **uninstall:** remove what was actually left behind ([f51826b](https://github.com/KasperSkytte/tradezulu/commit/f51826b8cbbb6991a8dd0c7fd64a858ecdc53783))


### Performance

* **agent:** compile the Expert Advisor once, not once per account ([a307387](https://github.com/KasperSkytte/tradezulu/commit/a307387b1ed342d2eb1baf45952a5a4fc03a667a))


### Refactoring

* **ui:** give the economic calendar its own page ([04d7a78](https://github.com/KasperSkytte/tradezulu/commit/04d7a784d78d6ad311980ce68a7063e50763cd5e))

## [1.13.0](https://github.com/KasperSkytte/tradezulu/compare/v1.12.0...v1.13.0) (2026-08-02)


### Features

* **dashboard:** add an economic calendar, high-impact dollar news by default ([3a0cded](https://github.com/KasperSkytte/tradezulu/commit/3a0cded947d9045a99ae70d6d2e29ea7f0ffcae9))

## [1.12.0](https://github.com/KasperSkytte/tradezulu/compare/v1.11.0...v1.12.0) (2026-08-02)


### Features

* **agent:** set the weekly restart window from the web interface ([7a779aa](https://github.com/KasperSkytte/tradezulu/commit/7a779aa6a0efe5593eb6a5ead11467072b8cfc1f))
* **charts:** work the TradingView exchange prefix out from the broker ([8cb49ba](https://github.com/KasperSkytte/tradezulu/commit/8cb49ba39714bfe644a540daba0c8b8ac2c5ba54))
* **dashboard:** show percentages rather than money by default ([1790d1b](https://github.com/KasperSkytte/tradezulu/commit/1790d1b59a1d235bba89f01b3f755ebbc1bde422))
* **export:** give exporting its own card, covering every account ([0e41785](https://github.com/KasperSkytte/tradezulu/commit/0e41785d9ff40f446c609335f430cdf5dc3252fb))
* **metrics:** replace drawdown with how even the losses were ([8a72eb2](https://github.com/KasperSkytte/tradezulu/commit/8a72eb2627d0e1164495ec454b70c8705b4a16e3))
* **risk:** stop inventing risk for trades that never had a stop ([b5bf762](https://github.com/KasperSkytte/tradezulu/commit/b5bf762592175a1c36e0609691ad8191920fa7b6))
* **tags:** make the tag groups adjustable ([e191812](https://github.com/KasperSkytte/tradezulu/commit/e191812b91d67f0dfad38af0923dd2314e48ad1d))


### Bug fixes

* **agent:** measure the Options dialog instead of guessing where it is ([fd9e815](https://github.com/KasperSkytte/tradezulu/commit/fd9e815ae448f0803e2c22941b4ef8e20264bc91))
* **import:** read MetaTrader reports by layout, and accept the spreadsheet ([1885d77](https://github.com/KasperSkytte/tradezulu/commit/1885d77f32c61ee56ce51ab82dcb07b960adb3bf))


### Refactoring

* **ui:** put MetaTrader with the accounts it feeds ([423e3af](https://github.com/KasperSkytte/tradezulu/commit/423e3af700822e75bf9394dc92a5d2697b3f80e4))

## [1.11.0](https://github.com/KasperSkytte/tradezulu/compare/v1.10.0...v1.11.0) (2026-07-31)


### Features

* **agent:** add a script for looking at the terminals ([3b9e173](https://github.com/KasperSkytte/tradezulu/commit/3b9e173619ff06a863de5853b9b9208f5ddf3e06))


### Bug fixes

* **agent:** add the missing re import ([87d7f71](https://github.com/KasperSkytte/tradezulu/commit/87d7f714b13fedf84f1db76c03868b172b54a393))
* **mt5:** require a password when the stored account is changed ([a3a1572](https://github.com/KasperSkytte/tradezulu/commit/a3a157244fee0634f6d76c7d11ae2b993a871829))

## [1.10.0](https://github.com/KasperSkytte/tradezulu/compare/v1.9.2...v1.10.0) (2026-07-31)


### Features

* **agent:** bring an archived account back as master when its credentials return ([cff24c5](https://github.com/KasperSkytte/tradezulu/commit/cff24c5b68ad53d509580979c34672e17d87f53e))


### Bug fixes

* **uninstall:** tear the whole compose stack down, not only what the file still lists ([31b93a6](https://github.com/KasperSkytte/tradezulu/commit/31b93a6382a6c535f507dac1dd689b2ccfbf874b))

## [1.9.2](https://github.com/KasperSkytte/tradezulu/compare/v1.9.1...v1.9.2) (2026-07-31)


### Bug fixes

* **accounts:** make forgetting an account delete its history ([2970594](https://github.com/KasperSkytte/tradezulu/commit/2970594fbbe8fbef00732a70ea2ef2c8c776248b))
* **agent:** give a new master account its own row instead of the old one's ([7f8ff3f](https://github.com/KasperSkytte/tradezulu/commit/7f8ff3f3b0e876b4935f1418cf8bd8ea6636cf9d))
* **stats:** scope the equity series to one account and rebase it to the window ([85b23b6](https://github.com/KasperSkytte/tradezulu/commit/85b23b6636dde2fe61cbb07df27ee04653c7611e))

## [1.9.1](https://github.com/KasperSkytte/tradezulu/compare/v1.9.0...v1.9.1) (2026-07-31)


### Bug fixes

* **copier:** make the minimum-lot setting actually rescue a small size ([449b91d](https://github.com/KasperSkytte/tradezulu/commit/449b91d5fe3c624b9c3dcbb490a8cde825f1de7e)), closes [#20](https://github.com/KasperSkytte/tradezulu/issues/20)
* **stats:** scope the journal to one account, and withhold what several cannot mean ([7e79af1](https://github.com/KasperSkytte/tradezulu/commit/7e79af12dc6da5f52969e9612fedab1060e27bd9))

## [1.9.0](https://github.com/KasperSkytte/tradezulu/compare/v1.8.2...v1.9.0) (2026-07-31)


### Features

* **copier:** size by a percentage of balance, and drop the extra scaling factor ([d0fb2cc](https://github.com/KasperSkytte/tradezulu/commit/d0fb2cc9616b1bd7bb5c2e17d1d3c4e439776699))
* **copier:** work the broker's symbol naming out from its own symbol list ([79f2741](https://github.com/KasperSkytte/tradezulu/commit/79f274130b1ded6a955fd843880075c4f93d3863))


### Refactoring

* **ui:** move the installation facts out of the MetaTrader settings ([35aa60b](https://github.com/KasperSkytte/tradezulu/commit/35aa60be2fae5c6812a60a40968b41bf93b6df4d))
* **ui:** rework the slave account settings ([4f4d7b2](https://github.com/KasperSkytte/tradezulu/commit/4f4d7b2c376c09b361b6d8a5b5552699c81465c3))


### Documentation

* move all but the dashboard screenshot to a page of its own ([f825d6e](https://github.com/KasperSkytte/tradezulu/commit/f825d6ead1949a16f919a204cbeff476aeac793d))
* refresh the screenshots ([3e24caf](https://github.com/KasperSkytte/tradezulu/commit/3e24caf4803b5ad8b84271359dd7b0552f899385))

## [1.8.2](https://github.com/KasperSkytte/tradezulu/compare/v1.8.1...v1.8.2) (2026-07-31)


### Bug fixes

* **copier:** count the account's real positions in the exposure limits ([11297c5](https://github.com/KasperSkytte/tradezulu/commit/11297c5375f2db80fded4c4038ff5807e3efcf66))
* **copier:** read banked profit for the daily target and consistency cap ([03a1b23](https://github.com/KasperSkytte/tradezulu/commit/03a1b2365634dda1638da186c32fd0a45621897a))
* **pwa:** reload the page when a new service worker takes over ([fd21315](https://github.com/KasperSkytte/tradezulu/commit/fd21315e4d903163ab2c795c6a5b4181fd64add5))
* **ui:** put the toggle knob back inside its track ([c01a62d](https://github.com/KasperSkytte/tradezulu/commit/c01a62d0f2c1f266512ab5850e40fabe3e556956))


### Refactoring

* **ui:** drop the version from the sidebar ([32a9d40](https://github.com/KasperSkytte/tradezulu/commit/32a9d40476b787c633fb21d691ff372311786e24))

## [1.8.1](https://github.com/KasperSkytte/tradezulu/compare/v1.8.0...v1.8.1) (2026-07-31)


### Bug fixes

* **agent:** start a terminal for every account that has credentials ([eabdda2](https://github.com/KasperSkytte/tradezulu/commit/eabdda2be56f9535e2115efacdb6d3093a86b6d4))
* **copier:** close dry-run links when a slave is taken live ([d746b73](https://github.com/KasperSkytte/tradezulu/commit/d746b737c900861d398afde86fb1a6081cb25f21))
* **copier:** record a standing skip once instead of on every poll ([24ea036](https://github.com/KasperSkytte/tradezulu/commit/24ea03616d591cfef3666c03d1042183c765e1d1))
* **copier:** reuse a master position's link instead of skipping when one exists ([249a354](https://github.com/KasperSkytte/tradezulu/commit/249a354a908ae8093c005faf84951a8b4bbc388e))


### Documentation

* drop the untested-copier caveat now that it has been run live ([8991f67](https://github.com/KasperSkytte/tradezulu/commit/8991f67a0f1d03cd0951654d72c026a48bb90bea)), closes [#10](https://github.com/KasperSkytte/tradezulu/issues/10)

## [1.8.0](https://github.com/KasperSkytte/tradezulu/compare/v1.7.0...v1.8.0) (2026-07-31)


### Features

* **stats:** measure a period against the balance it opened with ([9f92e82](https://github.com/KasperSkytte/tradezulu/commit/9f92e82542a4132e33088fb18f3b60353acf8c04))


### Bug fixes

* **calendar:** show the day's return, not its win rate ([d8bbb3b](https://github.com/KasperSkytte/tradezulu/commit/d8bbb3bf4557c88d931a9c378f0742bac26d2b86))
* **ui:** stop the page panning sideways on a phone ([842f15d](https://github.com/KasperSkytte/tradezulu/commit/842f15d00c0392338fef0e656a2c574756c8388a))


### Documentation

* refresh the screenshots and correct what they showed ([67dda38](https://github.com/KasperSkytte/tradezulu/commit/67dda38b4cd1ba8273282046cbca848409aa0e2a))

## [1.7.0](https://github.com/KasperSkytte/tradezulu/compare/v1.6.0...v1.7.0) (2026-07-31)


### Features

* **calendar:** show each day as a percentage of the account ([765e91e](https://github.com/KasperSkytte/tradezulu/commit/765e91ed67912dbd4a16a6faa187f8769631ecfa))
* **reports:** read a breakdown in money, R, or percent of the account ([f7380e5](https://github.com/KasperSkytte/tradezulu/commit/f7380e5e04982cda5d542ee00a8e2643acb6f9a7))
* **settings:** drop the configurable account size ([21b46f4](https://github.com/KasperSkytte/tradezulu/commit/21b46f40f65b88a7dc7ba6d595a3be54d529c5d0))
* **trades:** show each trade as a share of the balance it risked ([4448c31](https://github.com/KasperSkytte/tradezulu/commit/4448c31bc993a931f8af5ecd9866c8373e943ed5))


### Bug fixes

* **calendar:** measure a day against that morning's balance ([dd3fe9c](https://github.com/KasperSkytte/tradezulu/commit/dd3fe9c47de5a916fee2b3b97291779c3933083f))

## [1.6.0](https://github.com/KasperSkytte/tradezulu/compare/v1.5.0...v1.6.0) (2026-07-31)


### Features

* **mt5:** upload candles, so every trade has a chart to draw ([5c90f38](https://github.com/KasperSkytte/tradezulu/commit/5c90f382317fc000561fcd88a4b88deb7dfea5dc))
* **stats:** draw equity beside balance, and fix invisible popovers ([44031f7](https://github.com/KasperSkytte/tradezulu/commit/44031f78618e7673b68538bc93e88fa6632fa62e))

## [1.5.0](https://github.com/KasperSkytte/tradezulu/compare/v1.4.0...v1.5.0) (2026-07-31)


### Features

* **mt5:** pick a broker and its server, and say when a terminal is starting ([e79a545](https://github.com/KasperSkytte/tradezulu/commit/e79a545fbca87e40cb80e533f1e775b8c7f39480))
* **mt5:** real server lists, from the terminal's own search ([57165f9](https://github.com/KasperSkytte/tradezulu/commit/57165f97a02f1200902559fc13b8d84faeba517a))
* **stats:** breakeven by percent of account, and W/L/BE on the curve ([5ff8b15](https://github.com/KasperSkytte/tradezulu/commit/5ff8b15ce0df5d09174dedaeed8068db964c7f71))
* **trades:** tag a batch with several tags at once, grouped by kind ([b9b995a](https://github.com/KasperSkytte/tradezulu/commit/b9b995a492f864eda0e7d3fb0f6cf6ea2028fa19))
* **ui:** explain the jargon, and give breakevens their own colour ([457ead6](https://github.com/KasperSkytte/tradezulu/commit/457ead64558fa43ddb59506f734ba4662184354f))


### Bug fixes

* **install:** drop privilege correctly when already root ([afdc4f2](https://github.com/KasperSkytte/tradezulu/commit/afdc4f27fe5395726bbef74601742ca7777c6497))

## [1.4.0](https://github.com/KasperSkytte/tradezulu/compare/v1.3.0...v1.4.0) (2026-07-31)


### Features

* **install:** add an uninstaller that cannot delete the wrong thing ([f6042c7](https://github.com/KasperSkytte/tradezulu/commit/f6042c7ff89317788d31ae7269b8513ed60f0a85))
* **install:** let a service account own and run the terminals ([d41b25a](https://github.com/KasperSkytte/tradezulu/commit/d41b25ac26c834540dbe23af18334fb198e3eebf))


### Bug fixes

* **install:** find the Wine build by pattern, and let the user read it ([561c4f1](https://github.com/KasperSkytte/tradezulu/commit/561c4f12b06c8754cb4f09f5bad48d3925888f4c))
* **install:** give the agent a runtime directory of its own ([5436b75](https://github.com/KasperSkytte/tradezulu/commit/5436b75394de4df3138f98fb0598cbd21e4ed42b))
* **install:** install the agent as a system service ([2b12251](https://github.com/KasperSkytte/tradezulu/commit/2b122510e73368971f5f5f315a39445595bc903a))

## [1.3.0](https://github.com/KasperSkytte/tradezulu/compare/v1.2.1...v1.3.0) (2026-07-31)


### Features

* **agent:** let the master terminal claim its own account row ([8c95c3a](https://github.com/KasperSkytte/tradezulu/commit/8c95c3acf48ee018188ad088dd39d1618cd3642a))
* **agent:** provision a terminal per account without anyone configuring it ([b5d3b9b](https://github.com/KasperSkytte/tradezulu/commit/b5d3b9b9789754a58a43a34d78bce8afc3f875da))
* **agent:** restart terminals weekly, and drop the containerised bridge ([b02f351](https://github.com/KasperSkytte/tradezulu/commit/b02f3513cb5a38961a99b1de24daee666a548e39))
* **copier:** drive the terminals with an Expert Advisor, not the Python API ([5eaf27b](https://github.com/KasperSkytte/tradezulu/commit/5eaf27bbf313edfdf3ad789e12dc437d1c381297))
* **install:** set up a server from one script, terminals included ([c5db917](https://github.com/KasperSkytte/tradezulu/commit/c5db917c946cd2b3c7c367c59819f9260c42f130))
* **mt5:** send closed deals, so the journal fills itself ([9ff0597](https://github.com/KasperSkytte/tradezulu/commit/9ff0597f942d41edd6d0051f8d3ee3aad19d519e))


### Bug fixes

* **agent:** make a provisioned terminal actually run its expert ([e4b0f4d](https://github.com/KasperSkytte/tradezulu/commit/e4b0f4d22cac841b6e30ae8872265acb37264f5a))
* **mt5-bridge:** prefer IPv4, and ship the tools needed to see the terminal ([b5c368b](https://github.com/KasperSkytte/tradezulu/commit/b5c368b1fc2021a60a2cfa22bf6ed352db70df43))


### Documentation

* correct the WoW64 theory -- the installer is 64-bit ([2e6831d](https://github.com/KasperSkytte/tradezulu/commit/2e6831dfaa7fe7a8650e09604f9b2138aba4bb91))
* MetaQuotes' own Linux recipe, and where following it stops ([d0e378f](https://github.com/KasperSkytte/tradezulu/commit/d0e378f7e64ccff827fb3b222ea5559ca256e36f))
* native winhttp/wininet do not help either ([1b66c53](https://github.com/KasperSkytte/tradezulu/commit/1b66c53c502662b3da146f0151df5ee47ca916d0))
* point at the issue tracker, and name the three that matter ([cb88960](https://github.com/KasperSkytte/tradezulu/commit/cb88960db2ca9645f1a7f93361de07e1bd63dfc9))
* the GUI works and the login dialog was the blocker; the network is not ([c5f540b](https://github.com/KasperSkytte/tradezulu/commit/c5f540b276723928234be29f711f3779ddbf8816))
* the staging image has no WoW64, which is why the recipe cannot finish ([6177cd1](https://github.com/KasperSkytte/tradezulu/commit/6177cd1eca34253c99079f3a1d5bb54b6255b4e2))
* the terminal never authorises, so the EA route is closed too ([af05d5e](https://github.com/KasperSkytte/tradezulu/commit/af05d5e8251d6313138eda56f12653c7f9502965))

## [1.2.1](https://github.com/KasperSkytte/tradezulu/compare/v1.2.0...v1.2.1) (2026-07-29)


### Documentation

* mt5linux tested end to end, and it does not fix this ([ad096d2](https://github.com/KasperSkytte/tradezulu/commit/ad096d273293d5cf5f4c8f60fbcdda215e95016f))
* the terminal never serves the API, and non-root is required ([b1b125c](https://github.com/KasperSkytte/tradezulu/commit/b1b125c52740f417975cda39f08fd583c3986de0))

## [1.2.0](https://github.com/KasperSkytte/tradezulu/compare/v1.1.0...v1.2.0) (2026-07-28)


### Features

* **copier:** accounts API and the Accounts page ([b8af013](https://github.com/KasperSkytte/tradezulu/commit/b8af013a829895218625a9a641b4caf223b6c540))
* **copier:** execution layer, copy loop and a worker per account ([3570021](https://github.com/KasperSkytte/tradezulu/commit/3570021c038c1cca07f99325f2058be51d9f39d4))
* **mt5-bridge:** find a broker's own terminal, and pin the package version ([4b2fe2a](https://github.com/KasperSkytte/tradezulu/commit/4b2fe2a8f5c1b041d358aaf0ea9dafe560d311d7))


### Bug fixes

* **mt5-bridge:** do not crash on a fresh volume, and note the login finding ([a4973df](https://github.com/KasperSkytte/tradezulu/commit/a4973df5e46625a7164d78d09c170e271269beab))
* **mt5-bridge:** full Python install, Mono, win10, and honest readiness ([b4ce5f5](https://github.com/KasperSkytte/tradezulu/commit/b4ce5f56943064fa785b1791724c88d8bf1d034c))
* **mt5-bridge:** let the Python API own the terminal, and record what is ruled out ([bf3bd15](https://github.com/KasperSkytte/tradezulu/commit/bf3bd15ec676218dd81d3b2d1975539137823d2e))
* **mt5-bridge:** re-discover the terminal after a broker installer runs ([02e397a](https://github.com/KasperSkytte/tradezulu/commit/02e397a5c664537f82b559b35a200b34e9d32a55))
* **mt5-bridge:** run a window manager, and keep downloads off /tmp ([e5e0799](https://github.com/KasperSkytte/tradezulu/commit/e5e0799c2042fb29eadc18a2eaea8027db687f9c))


### Documentation

* write up the bridge IPC failure and stop claiming it works ([52e2bc8](https://github.com/KasperSkytte/tradezulu/commit/52e2bc89d6cbcd606fb50687b873f5ee614b68ac))

## [1.1.0](https://github.com/KasperSkytte/tradezulu/compare/v1.0.0...v1.1.0) (2026-07-27)


### Features

* **auth:** a way back in when TZ_ADMIN_USER no longer matches ([272c8b4](https://github.com/KasperSkytte/tradezulu/commit/272c8b478f44af28b9b4b264dac68794c5081140))


### Bug fixes

* **mt5-bridge:** pin Wine 10, update the prefix, and stop killing a live terminal ([e8daffd](https://github.com/KasperSkytte/tradezulu/commit/e8daffd16c05b19a6eab1383329f0578604f1bb5))

## 1.0.0 (2026-07-27)


### ⚠ BREAKING CHANGES

* **mt5:** the default sync mode is now 'bridge' rather than 'ea'. Existing installs keep whatever is stored in their settings.

### Features

* **backend:** trading journal API with MT5 sync, metrics and Zulu Score ([75b740c](https://github.com/KasperSkytte/tradezulu/commit/75b740ce93857a43d18738e0ae239187ee3bdf00))
* **ci:** GitHub Actions for lint, tests, image build and a container smoke ([c26f4e2](https://github.com/KasperSkytte/tradezulu/commit/c26f4e2f7a18a34c323e9adbc2df803d26f15d7a))
* **copier:** risk, sizing and copy-decision engine ([b5955f9](https://github.com/KasperSkytte/tradezulu/commit/b5955f9c39952243274faae385f32e1ac6e3b6ab))
* **docker:** single-container image, compose file and entrypoint ([c26f4e2](https://github.com/KasperSkytte/tradezulu/commit/c26f4e2f7a18a34c323e9adbc2df803d26f15d7a))
* **frontend:** dashboard, trades, calendar, reports and settings UI ([3be1329](https://github.com/KasperSkytte/tradezulu/commit/3be13294a2972d4e7441de29d812047b3e86f3df))
* **mt5:** Expert Advisor, optional Wine bridge and file import ([c26f4e2](https://github.com/KasperSkytte/tradezulu/commit/c26f4e2f7a18a34c323e9adbc2df803d26f15d7a))
* **mt5:** sync with just a server, account number and investor password ([170833d](https://github.com/KasperSkytte/tradezulu/commit/170833dd87af5d14fc1b898db98ab912ebb718da))
* **ui:** jade green accent, and position TradeZulu as copier plus journal ([0298a5a](https://github.com/KasperSkytte/tradezulu/commit/0298a5a08dd35226fdedbce025f9fd3e8beaba58))


### Bug fixes

* **charts:** give the TradingView widget a height it can resolve ([de65c83](https://github.com/KasperSkytte/tradezulu/commit/de65c8347e800acac029ada76e287bb774c20e3f))
* **charts:** render the trade replay and clean up derived money values ([d56dd47](https://github.com/KasperSkytte/tradezulu/commit/d56dd47123ae8c9b8facc9648f41aceaddcc6b1c))
* **db:** reconcile the schema on start so upgrades do not break ([e96617f](https://github.com/KasperSkytte/tradezulu/commit/e96617f0c70828a958127bf2c2b2ba7194c4a8ec))
* **mt5-bridge:** make the Wine container actually able to run MetaTrader ([0ab2153](https://github.com/KasperSkytte/tradezulu/commit/0ab21532150aef098db95442435f13ea5f65d335))
* **settings:** follow hash changes so deep links switch section ([3e5623e](https://github.com/KasperSkytte/tradezulu/commit/3e5623e8879f9adb16c33df85347ee50f9aad64a))


### Documentation

* make the compose image variables explicit in .env.example ([3e5623e](https://github.com/KasperSkytte/tradezulu/commit/3e5623e8879f9adb16c33df85347ee50f9aad64a))
* README, MetaTrader guide, metric definitions and deployment notes ([c26f4e2](https://github.com/KasperSkytte/tradezulu/commit/c26f4e2f7a18a34c323e9adbc2df803d26f15d7a))
* the README now leads with what this actually is — a trade copier and a ([0298a5a](https://github.com/KasperSkytte/tradezulu/commit/0298a5a08dd35226fdedbce025f9fd3e8beaba58))
* tighten the README for a public repo ([4f69491](https://github.com/KasperSkytte/tradezulu/commit/4f694911cbf91cd97195e3a543fae44f50a29297))


### Build & packaging

* **docker:** build the frontend on the native platform in multi-arch builds ([3e5623e](https://github.com/KasperSkytte/tradezulu/commit/3e5623e8879f9adb16c33df85347ee50f9aad64a))
* **docker:** mark the entrypoint executable ([b8b0a3d](https://github.com/KasperSkytte/tradezulu/commit/b8b0a3d7f7e0ef544480c51c2d2017528f1c9a59))
