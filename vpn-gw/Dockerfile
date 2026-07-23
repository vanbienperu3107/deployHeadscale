# vpn-gw — image cong (gateway) giu phien OpenVPN + HTTP forward-proxy.
#
# Muc dich: mot node giu ket noi OpenVPN toi mang Bitel thuong truc; cac peer
# tailnet tro PAC toi proxy nay de vao trang split-horizon (vd jump.bitel.com.pe)
# ma khong may nao phai tu chay OpenVPN. Xem docs/plan-vpn-gateway-bitel.md.
#
# Image KHONG chua tailscale: chay chung netns voi sidecar tailscale chinh thuc
# (compose network_mode: service:ts-vpngw) de proxy nam tren IP 100.x cua node.
FROM alpine:3.20

# openvpn: giu tun0. tinyproxy: HTTP/HTTPS forward-proxy (CONNECT). dnsmasq:
# split-DNS (*.bitel.com.pe -> DNS noi bo, con lai -> public). iptables: kill-switch.
# curl/bind-tools: health + debug. bash: entrypoint.
RUN apk add --no-cache \
      openvpn \
      tinyproxy \
      dnsmasq \
      iptables \
      curl \
      bind-tools \
      bash \
      tzdata \
 && rm -rf /var/cache/apk/*

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY tinyproxy.conf.tmpl /etc/vpn-gw/tinyproxy.conf.tmpl
# Strip CR neu file bi checkout CRLF tren Windows (shebang \r lam bash fail).
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh /etc/vpn-gw/tinyproxy.conf.tmpl \
 && chmod +x /usr/local/bin/entrypoint.sh \
 && mkdir -p /config /run/vpn-gw /var/log/vpn-gw

# Proxy port (mo trong netns dung chung voi sidecar tailscale).
EXPOSE 8888

# Healthcheck: proxy con song + (neu bat) tun0 con len. Chi tiet trong entrypoint.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD /usr/local/bin/entrypoint.sh healthcheck || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["run"]
