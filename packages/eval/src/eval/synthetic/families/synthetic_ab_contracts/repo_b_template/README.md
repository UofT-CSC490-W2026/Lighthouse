# providerlib

`providerlib` is the shared library repo for the synthetic A/B contract benchmark.

It intentionally exposes a handful of tiny helper APIs whose contracts are easy to
state but easy for a consumer to misuse:

- `providerlib.metrics.clamp_percentage`
- `providerlib.metrics.seconds_to_timeout_ms`
- `providerlib.http.parse_retry_header`
- `providerlib.http.parse_feature_flag`
- `providerlib.identity.normalize_username`
- `providerlib.identity.choose_primary_email`
- `providerlib.identity.normalize_tags`
- `providerlib.math_utils.safe_divide`
- `providerlib.cache.build_cache_key`
- `providerlib.ui.status_to_color`

The benchmark tasks mutate the consumer repo `A` so its tests fail while `providerlib`
remains correct.
