class Antigravity < Formula
  desc "Google Antigravity CLI Agent"
  homepage "https://antigravity.google"
  version "1.0.14"
  license ":cannot_represent"

  on_macos do
    if Hardware::CPU.arm?
      url "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.0.14-6049473256882176/darwin-arm/cli_mac_arm64.tar.gz"
      sha256 "44fb1db46b67d8566fdafe31ff44722c02ad1655d588cc18029ee349122bb3a3"
    else
      url "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.0.14-6049473256882176/darwin-x64/cli_mac_x64.tar.gz"
      sha256 "75a2840202f67a25396b5fb758ab77c212636a6a0e934a5b4175c49e79ae6df4"
    end
  end

  on_linux do
    if Hardware::CPU.arm?
      url "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.0.14-6049473256882176/linux-arm/cli_linux_arm64.tar.gz"
      sha256 "992653b4de4fe667ee5bd66ca259edd6b88b308f20a31880a77002624204e277"
    else
      url "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.0.14-6049473256882176/linux-x64/cli_linux_x64.tar.gz"
      sha256 "7170d598193ee0addcaba7d8c3a2c2e307ae8622dacf749831128bd1ad3ca458"
    end
  end

  def install
    # The tarball contains a single precompiled binary named "antigravity"
    bin.install "antigravity"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/antigravity --version")
  end
end
