//! Elidia Agent mobile shell.
//!
//! The app is a client of the user's own gateway, so this process holds no
//! agent logic: it hosts the webview and provides the one thing a browser
//! cannot, persistent storage for the pairing, through tauri-plugin-store.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::new().build())
        .run(tauri::generate_context!())
        .expect("error while running Elidia Agent");
}
