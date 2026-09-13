// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Netlink Socket Listener
 *
 * 封装 Linux 用户态 AF_NETLINK 套接字操作，绑定多播组 1 并接收事件。
 */

use crate::protocol::{ActionKeyEvent, ACTION_KEY_NL_GROUP, NETLINK_ACTION_KEY};
use std::io::{Error, Result};
use std::mem;

pub struct NetlinkListener {
    fd: libc::c_int,
}

impl NetlinkListener {
    /// 创建并绑定 Netlink 套接字
    pub fn bind() -> Result<Self> {
        let fd = unsafe {
            libc::socket(
                libc::AF_NETLINK,
                libc::SOCK_RAW | libc::SOCK_CLOEXEC,
                NETLINK_ACTION_KEY,
            )
        };

        if fd < 0 {
            return Err(Error::last_os_error());
        }

        // 绑定到多播组 1
        let mut sa: libc::sockaddr_nl = unsafe { mem::zeroed() };
        sa.nl_family = libc::AF_NETLINK as u16;
        sa.nl_pid = 0; // 内核会分配合适的 PID / 端口
        sa.nl_groups = ACTION_KEY_NL_GROUP; // 组 1

        let ret = unsafe {
            libc::bind(
                fd,
                &sa as *const libc::sockaddr_nl as *const libc::sockaddr,
                mem::size_of::<libc::sockaddr_nl>() as libc::socklen_t,
            )
        };

        if ret < 0 {
            let err = Error::last_os_error();
            unsafe { libc::close(fd) };
            return Err(err);
        }

        Ok(Self { fd })
    }

    /// 阻塞等待并读取一个手势事件
    pub fn recv_event(&self) -> Result<ActionKeyEvent> {
        let mut buffer = [0u8; 512];
        let bytes_read = unsafe {
            libc::recv(
                self.fd,
                buffer.as_mut_ptr() as *mut libc::c_void,
                buffer.len(),
                0,
            )
        };

        if bytes_read < 0 {
            return Err(Error::last_os_error());
        }

        let nl_msg_hdr_len = mem::size_of::<libc::nlmsghdr>();
        let event_len = mem::size_of::<ActionKeyEvent>();

        if (bytes_read as usize) < nl_msg_hdr_len + event_len {
            return Err(Error::new(
                std::io::ErrorKind::InvalidData,
                "接收到的 Netlink 数据包尺寸过小",
            ));
        }

        // 解析 nlmsghdr 载荷
        let nlh = unsafe { &*(buffer.as_ptr() as *const libc::nlmsghdr) };
        if nlh.nlmsg_type == libc::NLMSG_ERROR as u16 {
            return Err(Error::new(
                std::io::ErrorKind::Other,
                "Netlink 返回 NLMSG_ERROR",
            ));
        }

        // 获取载荷偏移处的数据
        let payload_ptr = unsafe {
            buffer.as_ptr().add(nl_msg_hdr_len) as *const ActionKeyEvent
        };
        let event = unsafe { *payload_ptr };

        Ok(event)
    }
}

impl Drop for NetlinkListener {
    fn drop(&mut self) {
        if self.fd >= 0 {
            unsafe { libc::close(self.fd) };
        }
    }
}
