// Minimal typings for the PayPal JS SDK v6 surface we use (web-sdk/v6/core).
import type React from "react";

export interface PayPalOneTimeSession {
  start(options: { presentationMode: "auto" | "popup" | "modal" | "redirect" }, order: Promise<{ orderId: string }>): Promise<void>;
  hasReturned?(): boolean;
  resume?(): Promise<void>;
}

export interface PayPalEligibility {
  isEligible(method: "paypal" | "venmo" | "paylater" | "credit"): boolean;
}

export interface PayPalSdkInstance {
  findEligibleMethods(options: { currencyCode: string; amount?: string }): Promise<PayPalEligibility>;
  createPayPalOneTimePaymentSession(callbacks: {
    onApprove: (data: { orderId: string }) => Promise<void> | void;
    onCancel?: (data?: unknown) => void;
    onError?: (error: { code?: string; message?: string }) => void;
  }): PayPalOneTimeSession;
}

declare global {
  interface Window {
    paypal?: {
      createInstance(options: {
        clientId: string;
        components: string[];
        pageType?: string;
        locale?: string;
      }): Promise<PayPalSdkInstance>;
    };
  }
}

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "paypal-button": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        type?: "pay" | "checkout" | "buynow" | "subscribe";
      };
    }
  }
}
