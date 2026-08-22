# nix/overlays.nix — Expose pkgs.elidia-agent for external NixOS configs
{ inputs, ... }:
{
  flake.overlays.default = final: _: {
    elidia-agent = final.callPackage ./elidia-agent.nix {
      inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
      npm-lockfile-fix = inputs.npm-lockfile-fix.packages.${final.stdenv.hostPlatform.system}.default;
      rev = inputs.self.rev or null;
    };
  };
}
