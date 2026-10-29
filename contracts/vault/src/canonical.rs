//! Canonical API input types (SPEC-V1.1 §3, "Canonical numeric API inputs").
//!
//! Integers are JSON *strings* of ASCII decimal digits matching `0` or `[1-9][0-9]*`.
//! The grammar is checked on the decoded JSON string before any conversion, so signs,
//! whitespace, leading zeros, exponents, decimal points, hex and JSON numbers are all
//! rejected. near-sdk's `U64`/`U128` wrappers use `str::parse` and accept `+7`, so they
//! must not be used for inputs.
//!
//! Policy hashes are canonical base58 of exactly 32 bytes.

use near_sdk::serde::{de, Deserialize, Deserializer, Serialize, Serializer};
use std::fmt;

pub const U32_MAX_DIGITS: usize = 10;
pub const U64_MAX_DIGITS: usize = 20;
pub const U128_MAX_DIGITS: usize = 39;
/// base58 of 32 bytes is at most 44 characters; longer input is rejected before decoding.
pub const HASH32_B58_MAX_CHARS: usize = 44;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CanonError {
    Empty,
    TooLong,
    NonDigit,
    LeadingZero,
    Overflow,
}

/// Parse `0 | [1-9][0-9]*` with at most `max_digits` digits and value `<= max`.
pub fn parse_canonical_decimal(s: &str, max_digits: usize, max: u128) -> Result<u128, CanonError> {
    let b = s.as_bytes();
    if b.is_empty() {
        return Err(CanonError::Empty);
    }
    if b.len() > max_digits {
        return Err(CanonError::TooLong);
    }
    if !b.iter().all(u8::is_ascii_digit) {
        return Err(CanonError::NonDigit);
    }
    if b.len() > 1 && b[0] == b'0' {
        return Err(CanonError::LeadingZero);
    }
    let mut v: u128 = 0;
    for &c in b {
        v = v
            .checked_mul(10)
            .and_then(|v| v.checked_add(u128::from(c - b'0')))
            .ok_or(CanonError::Overflow)?;
    }
    if v > max {
        return Err(CanonError::Overflow);
    }
    Ok(v)
}

#[derive(Debug, PartialEq, Eq)]
pub enum Hash32Error {
    TooLong,
    NotBase58,
    WrongLength,
    NonCanonical,
}

/// Decode canonical base58 of exactly 32 bytes; re-encoding must reproduce the input.
pub fn parse_hash32_b58(s: &str) -> Result<[u8; 32], Hash32Error> {
    if s.len() > HASH32_B58_MAX_CHARS {
        return Err(Hash32Error::TooLong);
    }
    let bytes = near_sdk::bs58::decode(s)
        .into_vec()
        .map_err(|_| Hash32Error::NotBase58)?;
    let arr: [u8; 32] = bytes.try_into().map_err(|_| Hash32Error::WrongLength)?;
    if near_sdk::bs58::encode(arr).into_string() != s {
        return Err(Hash32Error::NonCanonical);
    }
    Ok(arr)
}

struct CanonVisitor {
    max_digits: usize,
    max: u128,
    what: &'static str,
}

impl de::Visitor<'_> for CanonVisitor {
    type Value = u128;

    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "a canonical decimal string ({})", self.what)
    }

    // serde_json hands escaped strings to `visit_str` already decoded, so the grammar
    // applies to the decoded value. Non-string JSON values fall through to serde's
    // default `invalid_type` error.
    fn visit_str<E: de::Error>(self, v: &str) -> Result<u128, E> {
        parse_canonical_decimal(v, self.max_digits, self.max)
            .map_err(|e| E::custom(format_args!("non-canonical {}: {:?}", self.what, e)))
    }
}

macro_rules! canon_int {
    ($name:ident, $t:ty, $digits:expr, $what:literal) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq)]
        pub struct $name(pub $t);

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                let v = d.deserialize_str(CanonVisitor {
                    max_digits: $digits,
                    max: <$t>::MAX as u128,
                    what: $what,
                })?;
                Ok($name(v as $t))
            }
        }

        // Serialization (used by near-sdk's generated `ext` stubs) emits the canonical form.
        impl Serialize for $name {
            fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
                s.serialize_str(&self.0.to_string())
            }
        }
    };
}

canon_int!(CanonU32, u32, U32_MAX_DIGITS, "u32");
canon_int!(CanonU64, u64, U64_MAX_DIGITS, "u64");
canon_int!(CanonU128, u128, U128_MAX_DIGITS, "u128");

/// A 32-byte hash supplied as canonical base58.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Hash32B58(pub [u8; 32]);

struct Hash32Visitor;

impl de::Visitor<'_> for Hash32Visitor {
    type Value = [u8; 32];

    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("a canonical base58 string of exactly 32 bytes")
    }

    fn visit_str<E: de::Error>(self, v: &str) -> Result<[u8; 32], E> {
        parse_hash32_b58(v).map_err(|e| E::custom(format_args!("invalid policy hash: {e:?}")))
    }
}

impl<'de> Deserialize<'de> for Hash32B58 {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_str(Hash32Visitor).map(Hash32B58)
    }
}

impl Serialize for Hash32B58 {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(&to_b58(&self.0))
    }
}

pub fn to_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 0x0f) as usize] as char);
    }
    s
}

pub fn to_b58(bytes: &[u8]) -> String {
    near_sdk::bs58::encode(bytes).into_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::serde_json;

    #[derive(Deserialize, Debug)]
    #[serde(crate = "near_sdk::serde", deny_unknown_fields)]
    struct Args {
        request_id: CanonU64,
    }

    fn id(json: &str) -> Result<u64, String> {
        serde_json::from_str::<Args>(json)
            .map(|a| a.request_id.0)
            .map_err(|e| e.to_string())
    }

    #[test]
    fn canonical_u64_accepts_only_canonical_strings() {
        assert_eq!(id(r#"{"request_id":"7"}"#), Ok(7));
        assert_eq!(id(r#"{"request_id":"0"}"#), Ok(0));
        assert_eq!(id(r#"{"request_id":"18446744073709551615"}"#), Ok(u64::MAX));
        // JSON escape decodes to "7" before the grammar check (Phase0_A R5 design assumption).
        assert_eq!(id(r#"{"request_id":"7"}"#), Ok(7));
        for bad in [
            r#"{"request_id":"+7"}"#,
            r#"{"request_id":"07"}"#,
            r#"{"request_id":"00"}"#,
            r#"{"request_id":" 7"}"#,
            r#"{"request_id":"7 "}"#,
            r#"{"request_id":7}"#,
            r#"{"request_id":"7.0"}"#,
            r#"{"request_id":"1e1"}"#,
            r#"{"request_id":"-7"}"#,
            r#"{"request_id":""}"#,
            r#"{"request_id":"0x7"}"#,
            r#"{"request_id":"18446744073709551616"}"#,
            r#"{"request_id":"123456789012345678901"}"#,
            r#"{"request_id":"７"}"#,
            r#"{"request_id":null}"#,
            r#"{"request_id":["7"]}"#,
            r#"{"request_id":"1","request_id":"2"}"#,
            r#"{"request_id":"1","extra":"x"}"#,
            r#"{}"#,
        ] {
            assert!(id(bad).is_err(), "accepted non-canonical input {bad}");
        }
    }

    #[test]
    fn canonical_u128_bounds() {
        let max = "340282366920938463463374607431768211455";
        assert_eq!(
            parse_canonical_decimal(max, U128_MAX_DIGITS, u128::MAX),
            Ok(u128::MAX)
        );
        assert_eq!(
            parse_canonical_decimal(
                "340282366920938463463374607431768211456",
                U128_MAX_DIGITS,
                u128::MAX
            ),
            Err(CanonError::Overflow)
        );
        assert_eq!(
            parse_canonical_decimal(
                "1000000000000000000000000000000000000000",
                U128_MAX_DIGITS,
                u128::MAX
            ),
            Err(CanonError::TooLong)
        );
        assert_eq!(
            parse_canonical_decimal("4294967296", U32_MAX_DIGITS, u32::MAX as u128),
            Err(CanonError::Overflow)
        );
    }

    #[test]
    fn hash32_requires_canonical_base58_of_32_bytes() {
        let tv1 = "Huh1JW694BmEy8JARZmcDGptfBWCw2whpnzE9NugpBKc";
        assert!(parse_hash32_b58(tv1).is_ok());
        // 45 characters: rejected by the length pre-check before decoding.
        assert_eq!(
            parse_hash32_b58(&format!("1{tv1}")),
            Err(Hash32Error::TooLong)
        );
        assert_eq!(
            parse_hash32_b58(&to_b58(&[0u8; 33])),
            Err(Hash32Error::WrongLength)
        );
        assert_eq!(
            parse_hash32_b58(&to_b58(&[7u8; 31])),
            Err(Hash32Error::WrongLength)
        );
        assert_eq!(parse_hash32_b58("0OIl"), Err(Hash32Error::NotBase58));
        assert_eq!(parse_hash32_b58(""), Err(Hash32Error::WrongLength));
        assert_eq!(parse_hash32_b58(&"1".repeat(45)), Err(Hash32Error::TooLong));
        // All-zero hash is 32 '1' characters and is canonical.
        assert_eq!(parse_hash32_b58(&"1".repeat(32)), Ok([0u8; 32]));
    }
}
