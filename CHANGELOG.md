# Changelog

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
