//! Persistent preference is independent of an existing session's identity.
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Multiplexer {
    #[default]
    Screen,
    Tmux,
}

/// Durable tmux instance identity, shared by record I/O and the local adapter.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(crate) struct TmuxIdentity {
    pub(crate) server_pid: u32,
    pub(crate) session_id: String,
    pub(crate) created: u64,
    pub(crate) socket_dev: u64,
    pub(crate) socket_ino: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(crate) struct TmuxLifecycle {
    pub(crate) pane_id: String,
    pub(crate) remain_on_exit: bool,
    pub(crate) boot_id: String,
    pub(crate) pid_namespace: u64,
}
impl Multiplexer {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Screen => "screen",
            Self::Tmux => "tmux",
        }
    }
    pub fn parse(value: &str) -> Result<Self, &'static str> {
        match value {
            "screen" => Ok(Self::Screen),
            "tmux" => Ok(Self::Tmux),
            _ => Err("unknown multiplexer"),
        }
    }
}
