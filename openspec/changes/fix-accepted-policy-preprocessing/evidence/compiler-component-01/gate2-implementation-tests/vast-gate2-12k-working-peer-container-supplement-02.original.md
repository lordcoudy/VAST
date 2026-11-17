**Required correction under the existing strict closed-object contract. This is not a Proxy-defense expansion.**

Frozen main remains **182,690 bytes / `c7edd00c6a0e27b46eb56941ab486e3d2a4c6b797c2b957840b7027f8f8e5909`**.

The affected checks are:

- Line **390**: `gate2Profile`.
- Line **406**: `gate2Complete` expected pins.
- Line **423**: `gate2Context`.

For each valid field set, these ordinary containers can satisfy `Object.keys` and field-value checks:

```js
Object.assign([], validFields)
Object.assign(function () {}, validFields)
Object.assign(new String(''), validFields)
```

Their nonenumerable intrinsic properties are invisible to `Object.keys`. The profile can therefore reach provider work before export rejects it. Expected pins/context may become valid primitive tuples and never reject the container.

Require an ordinary record shape before dependent work. A simple `typeof object && !Array.isArray` guard still admits boxed strings. Either require the established ordinary/null-prototype policy or reuse bounded canonical prevalidation, which already rejects these containers.

The compound unapplied patch should include:

- Zero-provider-call regressions for malformed profile and expected-pin containers.
- Pure rejection cases for malformed context containers.
- Positive ordinary-record cases and the existing null-prototype policy.
- The previously identified commit scalar-type checks.

No execution or edits performed. The manifest02 BLOCK remains applicable until corrected bytes are reviewed.
