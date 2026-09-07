class Antigravity < Formula
  desc "Google Antigravity CLI Agent"
  homepage "https://antigravity.google"
  version "1.0.14"
  license ":cannot_represent"

  on_macos do
    if Hardware::CPU.arm?
      url "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.0.14-6049473256882176/darwin-arm/cli_mac_arm64.tar.gz"
      sha256 "1415071b4e4f15c05e4fdb92542235c914295ab6e7f67bfc2691fad4b986b6c45fb06b5bcc2fde5f9429a89efcc246d1c444288491770a32f879c28595db7aff"
    else
      url "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.0.14-6049473256882176/darwin-x64/cli_mac_x64.tar.gz"
      sha256 "214668e2813c2846a7af90944fe9bcb0a43673f561768272bc04daf1961359a56b9c5732aca8428539700ac191aba9fc7378de5b54a065897cc32ab3d2a53fc5"
    end
  end

  on_linux do
    if Hardware::CPU.arm?
      url "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.0.14-6049473256882176/linux-arm/cli_linux_arm64.tar.gz"
      sha256 "b9a08c738c11a88afc33eefe40e5df26cbf8494029d8263e0d54e8a5dc7a6ef4516228e2f7b7ad8734d09e37c447ab108d96276ff8b67b7d7af1f04bb3d9d770"
    else
      url "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.0.14-6049473256882176/linux-x64/cli_linux_x64.tar.gz"
      sha256 "b950854e5e7ca88ed8595a472f4d655331275f9ddf2e9ebe3810f89c74c86d30e508cc08771ea42e0d112f65bf42f5680f4109e1aeedafc5d61f39d88ff66982"
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