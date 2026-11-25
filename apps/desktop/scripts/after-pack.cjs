/**
 * after-pack.cjs — electron-builder afterPack hook.
 *
 * HISTORICAL ROLE (now retired for Windows): this used to rcedit the Elidia
 * icon + identity onto the packed Windows Elidia.exe, because
 * build.win.signAndEditExecutable was set to `false` to dodge a winCodeSign
 * 7-Zip symlink crash on non-admin local Windows (see set-exe-identity.cjs).
 * That left the stock "Electron" icon, so this hook re-stamped it by hand.
 *
 * WHY IT NO LONGER EDITS WINDOWS: signing is now ON (signAndEditExecutable
 * removed => defaults to true) so electron-builder runs its OWN
 * signAndEditResources for win32 — which applies rcedit (icon, ProductName,
 * FileDescription, CompanyName from `author`, LegalTrademarks, copyright) and
 * THEN signs the exe in the same step. A second rcedit here — after that
 * signature is applied — would mutate the PE and INVALIDATE the Authenticode
 * signature we just paid to add. So Windows must not re-edit here.
 * electron-builder's native pass already stamps everything this hook used to:
 *   icon     <- build.icon ("assets/icon" -> assets/icon.ico)
 *   ProductName / FileDescription <- productName ("Elidia Agent")
 *   CompanyName <- author ("AiUtils"); LegalTrademarks <- build.win.legalTrademarks
 *
 * macOS/Linux are untouched: rcedit is a PE-resource editor and irrelevant
 * there (identity comes from Info.plist / the .desktop entry), so the hook
 * remains a no-op off Windows.
 */

exports.default = async function afterPack(context) {
  if (context.electronPlatformName === 'win32') {
    // Signed by electron-builder's signAndEditResources in the same pass —
    // do NOT rcedit again here or the Authenticode signature is invalidated.
    return
  }
}
