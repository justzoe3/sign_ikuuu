/* LibSodium crypto_box_seal format, using original TweetNaCl and blakejs. */
(function (root) {
  function join(a, b) {
    const out = new Uint8Array(a.length + b.length);
    out.set(a); out.set(b, a.length); return out;
  }
  root.sealForGitHub = function (publicKeyBase64, value) {
    const pk = Uint8Array.from(atob(publicKeyBase64), c => c.charCodeAt(0));
    if (pk.length !== 32) throw new Error('GitHub 公钥长度无效');
    const ephemeral = nacl.box.keyPair();
    const nonce = blake2b(join(ephemeral.publicKey, pk), null, 24);
    const message = new TextEncoder().encode(value);
    try {
      const box = nacl.box(message, nonce, pk, ephemeral.secretKey);
      return btoa(String.fromCharCode(...join(ephemeral.publicKey, box)));
    } finally {
      message.fill(0); ephemeral.secretKey.fill(0);
    }
  };
})(self);
